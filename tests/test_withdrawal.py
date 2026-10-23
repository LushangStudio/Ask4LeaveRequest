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
    assert row['status']=='pending' and row['documents']==[]
    assert row['approval'] is None
    assert {k:row['history'][0]['approval'][k] for k in before['approval']}==before['approval']
    assert row['withdrawal']['actor']=='counselor-c'
    for person in ['student-a','counselor-a','counselor-c']:
        login(client,person)
        assert client.get('/api/requests/'+rid).json()['status']=='pending'
        assert client.post(f'/api/requests/{rid}/retry').status_code==409
        for doc in documents:assert client.get('/api/documents/'+doc['id']).status_code==404
    assert approve(client,rid).status_code==200
    for doc in documents:assert client.get('/api/documents/'+doc['id']).status_code==404
    with Session(m.engine) as db:
        assert db.get(m.ApprovalSignature,rid)
        assert db.scalar(select(func.count()).select_from(m.ApprovalArchive))==1
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
    assert result['status']=='pending' and result['file_status']=='not_started'
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
    assert row['status']=='pending' and row['file_status']=='not_started'


def test_reapproval_cycles_preserve_history_and_reject_stale_preview(client):
    login(client);rid=submit(client)['id'];login(client,'counselor-a')
    stale=client.post(f'/api/requests/{rid}/preview',json={'opinion':'同意'}).json()['id']
    before=client.post(f'/api/requests/{rid}/decision',json={'outcome':'approved','opinion':'同意','preview_id':stale}).json()
    for cycle in range(2):
        body={'role':'counselor','reason':f'修正第{cycle+1}次'}
        row=client.post(f'/api/requests/{rid}/withdraw',json=body).json()
        assert row['status']=='pending' and len(row['history'])==cycle+1
        assert client.post(f'/api/requests/{rid}/withdraw',json=body).json()==row
        assert client.post(f'/api/requests/{rid}/decision',json={'outcome':'approved','opinion':'同意','preview_id':stale}).status_code==409
        assert client.get(f'/api/previews/{stale}/0').status_code==404
        assert approve(client,rid).status_code==200
        for doc in before['documents']:assert client.get('/api/documents/'+doc['id']).status_code==404
    client.post(f'/api/requests/{rid}/withdraw',json={'role':'counselor'})
    rejected=client.post(f'/api/requests/{rid}/decision',json={'outcome':'rejected','opinion':'需要补充材料'}).json()
    assert rejected['status']=='rejected' and len(rejected['history'])==3


def test_student_can_withdraw_reopened_request(client):
    login(client);rid=submit(client)['id'];login(client,'counselor-a');approve(client,rid)
    client.post(f'/api/requests/{rid}/withdraw',json={'role':'counselor'})
    login(client)
    row=client.post(f'/api/requests/{rid}/withdraw',json={'role':'student'}).json()
    assert row['status']=='withdrawn' and len(row['history'])==1
    assert row['withdrawal']['role']=='student'


def test_delayed_withdrawal_cannot_revoke_new_approval(client):
    login(client);rid=submit(client)['id'];login(client,'counselor-a')
    old=approve(client,rid).json()['approval']['at']
    body={'role':'counselor','approval_at':old}
    assert client.post(f'/api/requests/{rid}/withdraw',json=body).status_code==200
    assert approve(client,rid).status_code==200
    assert client.post(f'/api/requests/{rid}/withdraw',json=body).status_code==409
    assert client.get('/api/requests/'+rid).json()['status']=='approved'
