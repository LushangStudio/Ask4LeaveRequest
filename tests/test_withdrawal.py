from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app import main as m
from test_workflow import client, login, submit, payload, approve


def test_student_withdrawal_is_visible_and_terminal(client):
    login(client); rid=submit(client)['id']
    login(client,'student-b')
    assert client.post(f'/api/requests/{rid}/withdraw',json={}).status_code==404
    login(client,'counselor-a')
    preview=client.post(f'/api/requests/{rid}/preview',json={}).json()
    assert client.post(f'/api/requests/{rid}/withdraw',json={}).status_code==409
    login(client)
    body={'reason':'计划取消'}
    row=client.post(f'/api/requests/{rid}/withdraw',json=body).json()
    assert row['status']=='withdrawn' and row['file_status']=='cancelled'
    assert row['withdrawal']['actor']=='student-a' and row['documents']==[]
    assert client.post(f'/api/requests/{rid}/withdraw',json=body).json()==row
    for person in ['student-a','counselor-a','counselor-c']:
        login(client,person)
        assert client.get('/api/requests/'+rid).json()['status']=='withdrawn'
        assert rid in {r['id'] for r in client.get('/api/requests').json()}
        assert client.post(f'/api/requests/{rid}/retry').status_code==409
    assert client.get(f"/api/previews/{preview['id']}/0").status_code in {404,409}
    assert client.post(f'/api/requests/{rid}/preview',json={}).status_code==409
    assert approve(client,rid).status_code==409
    with Session(m.engine) as db:
        assert db.get(m.Decision,rid) is None
        assert db.scalar(select(func.count()).select_from(m.Withdrawal))==1


def test_counselor_revocation_retains_audit_and_disables_documents(client):
    login(client); rid=submit(client,payload('separate'))['id']
    login(client,'counselor-a'); before=approve(client,rid).json()
    documents=before['documents']; assert len(documents)==2
    login(client)
    assert client.post(f'/api/requests/{rid}/withdraw',json={}).status_code==409
    login(client,'counselor-b')
    assert client.post(f'/api/requests/{rid}/withdraw',json={}).status_code==404
    login(client,'counselor-c')
    row=client.post(f'/api/requests/{rid}/withdraw',json={'reason':'审批有误'}).json()
    assert row['status']=='revoked' and row['documents']==[]
    assert row['approval']==before['approval']
    assert row['withdrawal']['actor']=='演示辅导员丙'
    for person in ['student-a','counselor-a','counselor-c']:
        login(client,person)
        assert client.get('/api/requests/'+rid).json()['status']=='revoked'
        assert client.post(f'/api/requests/{rid}/retry').status_code==409
        for doc in documents:assert client.get('/api/documents/'+doc['id']).status_code==410
    assert approve(client,rid).status_code==409
    with Session(m.engine) as db:
        assert db.get(m.ApprovalSignature,rid)
        assert db.scalar(select(func.count()).select_from(m.Document).where(m.Document.request_id==rid))==2


def test_revocation_wins_over_in_progress_pdf_generation(client,monkeypatch):
    login(client);rid=submit(client)['id'];login(client,'counselor-a')
    original=m.render_pdf
    def render_and_revoke(*args,**kwargs):
        result=original(*args,**kwargs)
        with Session(m.engine) as db:
            actor=db.get(m.Person,'counselor-a')
            m.withdraw(rid,m.WithdrawalInput(reason='生成期间撤回'),db,actor)
        return result
    monkeypatch.setattr(m,'render_pdf',render_and_revoke)
    result=approve(client,rid).json()
    assert result['status']=='revoked' and result['file_status']=='cancelled'
    assert result['documents']==[]
    with Session(m.engine) as db:
        assert db.scalar(select(func.count()).select_from(m.Document))==0


def test_revoked_generation_failure_cannot_reset_cancelled_status(client,monkeypatch):
    login(client);rid=submit(client)['id'];login(client,'counselor-a')
    def fail_and_revoke(*args,**kwargs):
        with Session(m.engine) as db:
            m.withdraw(rid,m.WithdrawalInput(),db,db.get(m.Person,'counselor-a'))
        raise RuntimeError('simulated renderer failure')
    monkeypatch.setattr(m,'render_pdf',fail_and_revoke)
    row=approve(client,rid).json()
    assert row['status']=='revoked' and row['file_status']=='cancelled'
