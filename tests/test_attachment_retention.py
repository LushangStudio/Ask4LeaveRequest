from datetime import date
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app import main as m
from app import attachment_retention as retention
from test_workflow import client, login, payload, submit, approve
from test_attachments import attachment


def test_calendar_month_boundaries():
    for end, through in [('2026-01-31','2026-02-28'),('2028-01-31','2028-02-29'),('2026-12-31','2027-01-31'),('2026-10-22','2026-11-22')]:
        assert retention.retained_through(end).isoformat()==through
        assert not retention.expired(end,date.fromisoformat(through))
    assert retention.expired('2026-01-31',date(2026,3,1))


def test_purge_only_attachments_after_deadline_and_blocks_access(client,monkeypatch):
    login(client)
    body=payload();body['attachments']=[attachment()]
    row=submit(client,body);aid=row['attachments'][0]['id']
    login(client,'counselor-a');result=approve(client,row['id']).json()
    assert retention.purge(m.engine,date(2026,11,3))==0
    monkeypatch.setattr(retention,'today',lambda:date(2026,11,4))
    assert client.get('/api/attachments/'+aid).status_code==410
    assert client.get('/api/requests/'+row['id']).json()['attachments']==[]
    assert retention.purge(m.engine)==1
    assert retention.purge(m.engine)==0
    with Session(m.engine) as db:
        assert db.scalar(select(func.count()).select_from(m.Attachment))==0
        assert db.get(m.Request,row['id']) is not None
        assert db.get(m.Decision,row['id']) is not None
    assert client.get('/api/documents/'+result['documents'][0]['id']).status_code==200
