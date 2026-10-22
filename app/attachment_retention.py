"""Delete attachment bytes after the leave end date plus one calendar month.

Application/approval records and generated PDFs are deliberately retained.
"""
import calendar
import logging
import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def retained_through(end):
    end = date.fromisoformat(end) if isinstance(end, str) else end
    month = end.month % 12 + 1
    year = end.year + (end.month == 12)
    return date(year, month, min(end.day, calendar.monthrange(year, month)[1]))


def expired(end, on=None):
    return (on or today()) > retained_through(end)


def purge(engine, on=None):
    from app import main as m
    on = on or today()
    cursor = ''
    removed = 0
    # Scan metadata in bounded pages; never load attachment contents for cleanup.
    with Session(engine) as db:
        while True:
            rows = db.execute(select(m.Request.id, m.Request.ends).where(
                m.Request.id > cursor, m.Request.ends < on.isoformat(),
                select(m.Attachment.id).where(m.Attachment.request_id == m.Request.id).exists()
            ).order_by(m.Request.id).limit(200)).all()
            if not rows:
                break
            ids = [rid for rid, end in rows if expired(end, on)]
            if ids:
                result = db.execute(delete(m.Attachment).where(m.Attachment.request_id.in_(ids)))
                removed += result.rowcount
            db.commit()
            cursor = rows[-1][0]
    return removed


class Worker:
    def __init__(self, engine):
        self.engine = engine
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.loop, name='attachment-retention', daemon=True)
        self.thread.start()

    def loop(self):
        # Startup already purges synchronously. Subsequent cleanup is hourly.
        while not self.stopping.wait(3600):
            try:
                count = purge(self.engine)
                if count: logger.info('Deleted %s expired attachments', count)
            except Exception:
                logger.exception('Attachment retention cleanup failed; will retry next hour')

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=5)
