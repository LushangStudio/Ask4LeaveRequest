"""Database-backed PDF work with expiring leases and fenced atomic publication."""
import hashlib
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

LEASE_SECONDS = 300
MAX_ATTEMPTS = 3
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def async_enabled():
    # Production always uses durable jobs. Local demos can opt into the same
    # behavior; inline mode keeps standalone scripts deterministic.
    return os.getenv('APP_MODE') == 'production' or os.getenv('PDF_JOB_MODE') == 'async'


def enqueue(db, rid):
    from app import main as m
    row = db.get(m.Request, rid)
    if row.status != 'approved' or row.file_status == 'ready':
        return
    job = db.get(m.PDFJob, rid)
    if job is None:
        db.add(m.PDFJob(request_id=rid, state='queued', attempts=0, available=now()))
    else:
        # Concurrent retries cannot reset an active lease or its attempt count.
        db.execute(update(m.PDFJob).where(m.PDFJob.request_id==rid, m.PDFJob.state=='failed')
                   .values(state='queued', token=None, attempts=0, available=now(), lease_until=None))
    db.execute(update(m.Request).where(m.Request.id==rid, m.Request.status=='approved',
                                     m.Request.file_status.in_(['not_started','failed']))
               .values(file_status='generating', generation_error=None))


def seed_legacy_jobs(db):
    from app import main as m
    rows = db.scalars(select(m.Request).where(m.Request.status=='approved',
        m.Request.file_status.in_(['not_started','generating','failed']),
        ~select(m.PDFJob).where(m.PDFJob.request_id==m.Request.id).exists()))
    for row in rows:
        if row.file_status == 'failed':
            db.add(m.PDFJob(request_id=row.id,state='failed',attempts=MAX_ATTEMPTS,available=now()))
        else:
            enqueue(db, row.id)


def run_one(engine):
    from app import main as m
    stamp = now()
    eligible = or_((m.PDFJob.state=='queued') & (m.PDFJob.available<=stamp),
                   (m.PDFJob.state=='running') & (m.PDFJob.lease_until<=stamp))
    token = str(uuid.uuid4())
    with Session(engine) as db:
        rid = db.scalar(select(m.PDFJob.request_id).where(eligible).order_by(m.PDFJob.available).limit(1))
        if rid is None:
            return False
        claimed = db.execute(update(m.PDFJob).where(m.PDFJob.request_id==rid, eligible)
            .values(state='running', token=token, attempts=m.PDFJob.attempts+1,
                    lease_until=stamp+timedelta(seconds=LEASE_SECONDS))).rowcount
        db.commit()
        if not claimed:
            return True
        attempts = db.get(m.PDFJob, rid).attempts
    try:
        if attempts > MAX_ATTEMPTS:
            raise RuntimeError('PDF job exhausted crash recovery attempts')
        with Session(engine) as db:
            row = db.get(m.Request, rid)
            decision = db.get(m.Decision, rid)
            signature = db.get(m.ApprovalSignature, rid)
            items = list(db.scalars(select(m.Item).where(m.Item.request_id==rid).order_by(m.Item.position)))
            if row.status != 'approved' or row.file_status == 'ready':
                db.execute(update(m.PDFJob).where(m.PDFJob.request_id==rid,m.PDFJob.token==token)
                           .values(state='done',token=None,lease_until=None))
                db.commit()
                return True
            groups = [items] if row.layout=='combined' else [[item] for item in items]
            # No database transaction is held across expensive PDF rendering.
            db.expunge_all()
        documents = []
        for position, group in enumerate(groups):
            data = m.render_pdf(row, decision, group, signature.content if signature else None)
            documents.append(m.Document(id=str(uuid.uuid4()), request_id=rid, position=position,
                name=f'{uuid.uuid4().hex}.pdf', content=data, digest=hashlib.sha256(data).hexdigest()))
        with Session(engine) as db:
            # A replacement worker owns a new token. An expired/stale renderer
            # cannot publish, even if it eventually finishes successfully.
            owned = db.execute(update(m.PDFJob).where(m.PDFJob.request_id==rid,
                m.PDFJob.token==token,m.PDFJob.state=='running',m.PDFJob.lease_until>now())
                .values(state='done',token=None,lease_until=None)).rowcount
            if not owned:
                db.rollback()
                return True
            published = db.execute(update(m.Request).where(m.Request.id==rid,
                m.Request.status=='approved',m.Request.file_status=='generating')
                .values(file_status='ready',generation_error=None)).rowcount
            if published:
                db.add_all(documents)
            db.commit()
    except Exception:
        logger.exception('PDF background job failed for request %s', rid)
        with Session(engine) as db:
            retry = attempts < MAX_ATTEMPTS
            owned = db.execute(update(m.PDFJob).where(m.PDFJob.request_id==rid,
                m.PDFJob.token==token,m.PDFJob.state=='running')
                .values(state='queued' if retry else 'failed',token=None,lease_until=None,
                        available=now()+timedelta(seconds=10*2**(attempts-1)))).rowcount
            if owned and not retry:
                db.execute(update(m.Request).where(m.Request.id==rid,m.Request.status=='approved',
                    m.Request.file_status=='generating').values(file_status='failed',
                    generation_error='审批已通过，文件生成失败。可稍后重试或联系管理员。'))
            db.commit()
    return True


class Worker:
    def __init__(self, engine):
        self.engine = engine
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.loop, name='pdf-jobs', daemon=True)
        self.thread.start()

    def loop(self):
        while not self.stopping.is_set():
            try:
                busy = run_one(self.engine)
            except Exception:
                logger.exception('PDF worker database operation failed')
                busy = False
            self.stopping.wait(0.1 if busy else 1)

    def stop(self):
        self.stopping.set()
        # Remaining work is recovered using its lease after process termination.
        self.thread.join(timeout=5)


def start_worker():
    from app import main as m
    return Worker(m.engine)
