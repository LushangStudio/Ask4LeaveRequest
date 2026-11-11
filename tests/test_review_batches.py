import io
import zipfile

import pytest
from sqlalchemy import inspect, select, update
from sqlalchemy.orm import Session

from app import main as m
from app import pdf_jobs
from test_application_modes import mode_payload
from test_workflow import client, login, submit


def review(client, **filters):
    response = client.post('/api/requests/review-list', json=filters)
    assert response.status_code == 200, response.text
    return response.json()


def approval(client, ids, **overrides):
    signature = client.get('/api/signature').json()
    return client.post('/api/requests/batch-approve', json={
        'ids': ids, 'signature_version': signature['version'], **overrides,
    })


def test_search_and_pagination_only_show_assigned_requests(client):
    login(client)
    ids = []
    for index in range(21):
        body = mode_payload('items')
        body['reason'] = '学术交流' if index < 20 else '字面 100%'
        ids.append(submit(client, body)['id'])
    login(client, 'student-b')
    submit(client, mode_payload('items'))
    with Session(m.engine) as db:
        # Equal timestamps must still give stable, non-overlapping pages.
        db.execute(update(m.Request).values(created='2026-10-01T00:00:00+00:00'))
        row = db.get(m.Request, ids[-1])
        row.snapshot = {**row.snapshot, 'name': '分页测试姓名'}
        db.commit()
    assert client.post('/api/requests/review-list', json={}).status_code == 403
    login(client, 'counselor-a')
    for query in ['', '志愿者活动']:
        pages = [review(client, page=page, query=query) for page in [1, 2, 3]]
        assert [len(page['records']) for page in pages] == [10, 10, 1]
        assert all(page['total'] == 21 and page['pages'] == 3 for page in pages)
        assert [row['id'] for page in pages for row in page['records']] == sorted(ids, reverse=True)
    assert review(client, query='学术交流', page=2)['total'] == 20
    assert [row['id'] for row in review(client, query='测试姓名')['records']] == [ids[-1]]
    assert [row['id'] for row in review(client, query='%')['records']] == [ids[-1]]
    assert review(client, page=999)['page'] == 3
    assert review(client, query='查无此项')['records'] == []


def test_inclusive_day_filters_match_items_and_legacy_ranges(client):
    login(client)
    body = mode_payload('items')
    body['items'][1]['day'] = '2026-10-03'
    items = submit(client, body)['id']
    interval = submit(client, mode_payload('date_range'))['id']
    login(client, 'counselor-a')
    assert {row['id'] for row in review(client, starts='2026-10-02', ends='2026-10-02')['records']} == {interval}
    assert {row['id'] for row in review(client, starts='2026-10-03', ends='2026-10-03')['records']} == {items, interval}
    assert {row['id'] for row in review(client, query='志愿者', starts='2026-10-03')['records']} == {items}
    assert review(client, ends='2026-09-30')['total'] == 0
    assert client.post('/api/requests/review-list', json={'starts':'2026-10-04','ends':'2026-10-03'}).status_code == 422
    indexes = inspect(m.engine)
    assert {'ix_leave_requests_ends_starts', 'ix_leave_requests_created_id'} <= {item['name'] for item in indexes.get_indexes('leave_requests')}
    assert 'ix_leave_items_request_day' in {item['name'] for item in indexes.get_indexes('leave_items')}


def test_batch_approval_export_and_withdrawal(client):
    login(client)
    ids = [submit(client, mode_payload('items', layout))['id'] for layout in ['combined', 'separate']]
    login(client, 'counselor-a')
    assert client.post('/api/requests/batch-export', json={'ids': ids}).status_code == 409
    result = approval(client, ids, opinion='批量审批意见')
    assert result.status_code == 200, result.text
    assert result.json() == {'approved': 2}
    with Session(m.engine) as db:
        for rid in ids:
            assert db.get(m.Decision, rid).opinion == '批量审批意见'
            assert db.get(m.ApprovalSignature, rid).watermark == m.signature_watermark(db.get(m.Request, rid))
        documents = list(db.scalars(select(m.Document).where(m.Document.request_id.in_(ids))))
        expected = {f'{ids.index(doc.request_id)+1:02d}/{doc.id}.pdf': doc.content for doc in documents}
    response = client.post('/api/requests/batch-export', json={'ids': ids})
    assert response.status_code == 200 and response.headers['content-type'] == 'application/zip'
    assert response.headers['cache-control'] == 'no-store'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 3
        assert {name: archive.read(name) for name in archive.namelist()} == expected
    login(client, 'counselor-b')
    assert client.post('/api/requests/batch-export', json={'ids': ids}).status_code == 404
    login(client, 'student-a')
    assert client.post('/api/requests/batch-export', json={'ids': ids}).status_code == 403
    login(client, 'counselor-a')
    assert client.post(f'/api/requests/{ids[0]}/withdraw', json={}).status_code == 200
    assert client.post('/api/requests/batch-export', json={'ids': ids}).status_code == 409


def test_batch_rejects_stale_signature_unassigned_and_nonpending_rows(client):
    login(client)
    ids = [submit(client)['id'] for _ in range(2)]
    login(client, 'student-b')
    other = submit(client)['id']
    login(client, 'counselor-a')
    assert approval(client, [ids[0], other]).status_code == 404
    assert approval(client, ids, signature_version='00000000-0000-0000-0000-000000000000').status_code == 409
    assert approval(client, [ids[0], ids[0]]).status_code == 422
    assert approval(client, ids * 6).status_code == 422
    assert approval(client, [ids[1]]).status_code == 200
    assert approval(client, ids).status_code == 409
    assert client.get('/api/requests/' + ids[0]).json()['status'] == 'pending'
    with Session(m.engine) as db:
        assert db.get(m.Decision, ids[0]) is None


def test_batch_records_jobs_and_rolls_back_on_mid_batch_error(client, monkeypatch):
    login(client)
    ids = [submit(client)['id'] for _ in range(2)]
    login(client, 'counselor-a')
    monkeypatch.setattr(pdf_jobs, 'async_enabled', lambda: True)
    mark = m.watermarked_signature
    calls = 0

    def fail_on_second(content, watermark):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('simulated signature generation failure')
        return mark(content, watermark)

    with monkeypatch.context() as patch:
        patch.setattr(m, 'watermarked_signature', fail_on_second)
        with pytest.raises(RuntimeError, match='simulated signature'):
            approval(client, ids)
    with Session(m.engine) as db:
        for rid in ids:
            assert db.get(m.Request, rid).status == 'pending'
            assert db.get(m.Decision, rid) is None
            assert db.get(m.PDFJob, rid) is None
    assert approval(client, ids).json() == {'approved': 2}
    with Session(m.engine) as db:
        for rid in ids:
            assert db.get(m.Request, rid).file_status == 'generating'
            assert db.get(m.PDFJob, rid).state == 'queued'
