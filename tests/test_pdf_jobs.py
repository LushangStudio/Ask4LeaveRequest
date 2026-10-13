from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

import pytest
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session
from app import main as m, pdf_jobs as jobs
from test_workflow import client, login, submit, approve, payload


@pytest.fixture
def queued(client, monkeypatch):
    # Enable after lifespan, so tests control worker scheduling deterministically.
    monkeypatch.setenv('PDF_JOB_MODE','async')
    login(client);rid=submit(client,payload('separate'))['id']
    login(client,'counselor-a')
    row=approve(client,rid).json()
    assert row['status']=='approved' and row['file_status']=='generating' and row['documents']==[]
    return client,rid


def test_two_workers_and_duplicate_retry_publish_only_one_batch(queued,monkeypatch):
    c,rid=queued
    started=threading.Event();release=threading.Event()
    original=m.render_pdf
    def slow(*args):
        started.set();assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(m,'render_pdf',slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(jobs.run_one,m.engine)
        assert started.wait(5)
        assert pool.submit(jobs.run_one,m.engine).result() is False
        for _ in range(3):assert c.post(f'/api/requests/{rid}/retry').json()['file_status']=='generating'
        release.set();assert first.result()
    row=c.get('/api/requests/'+rid).json()
    assert row['file_status']=='ready' and len(row['documents'])==2
    assert not jobs.run_one(m.engine)
    assert c.post(f'/api/requests/{rid}/retry').json()['documents']==row['documents']
    with Session(m.engine) as db:assert db.get(m.PDFJob,rid).attempts==1


def test_expired_lease_recovered_and_old_worker_cannot_publish(queued,monkeypatch):
    c,rid=queued
    started=threading.Event();release=threading.Event()
    original=m.render_pdf
    worker_thread=[None]
    def slow(*args):
        if threading.get_ident()==worker_thread[0]:
            started.set();assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(m,'render_pdf',slow)
    def old_worker():
        worker_thread[0]=threading.get_ident()
        return jobs.run_one(m.engine)
    with ThreadPoolExecutor() as pool:
        first=pool.submit(old_worker);assert started.wait(5)
        with Session(m.engine) as db:
            db.get(m.PDFJob,rid).lease_until=jobs.now()-timedelta(seconds=1);db.commit()
        assert jobs.run_one(m.engine)
        before=c.get('/api/requests/'+rid).json()['documents']
        assert len(before)==2
        release.set();first.result()
    assert c.get('/api/requests/'+rid).json()['documents']==before


def test_partial_failure_retries_bounded_and_manual_retry(queued,monkeypatch):
    c,rid=queued;original=m.render_pdf;calls=[0]
    def fail_second(*args):
        calls[0]+=1
        if calls[0]%2==0:raise RuntimeError('deliberate second PDF failure')
        return original(*args)
    monkeypatch.setattr(m,'render_pdf',fail_second)
    for attempt in range(3):
        assert jobs.run_one(m.engine)
        with Session(m.engine) as db:
            assert db.scalar(select(func.count()).select_from(m.Document))==0
            db.get(m.PDFJob,rid).available=jobs.now()-timedelta(seconds=1);db.commit()
    row=c.get('/api/requests/'+rid).json()
    assert row['status']=='approved' and row['file_status']=='failed'
    assert not jobs.run_one(m.engine)
    monkeypatch.setattr(m,'render_pdf',original)
    assert c.post(f'/api/requests/{rid}/retry').json()['file_status']=='generating'
    jobs.run_one(m.engine)
    assert len(c.get('/api/requests/'+rid).json()['documents'])==2


def test_revocation_during_background_generation_prevents_publish(queued,monkeypatch):
    c,rid=queued;original=m.render_pdf
    def revoke(*args):
        c.post(f'/api/requests/{rid}/withdraw',json={'role':'counselor'})
        return original(*args)
    monkeypatch.setattr(m,'render_pdf',revoke)
    jobs.run_one(m.engine)
    row=c.get('/api/requests/'+rid).json()
    assert row['status']=='revoked' and row['file_status']=='cancelled' and row['documents']==[]
    with Session(m.engine) as db:assert db.scalar(select(func.count()).select_from(m.Document))==0


def test_real_worker_picks_up_persisted_job(queued):
    c,rid=queued
    worker=jobs.Worker(m.engine)
    try:
        import time
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            row=c.get('/api/requests/'+rid).json()
            if row['file_status']=='ready':break
            time.sleep(.05)
        assert row['file_status']=='ready'
    finally:worker.stop()
