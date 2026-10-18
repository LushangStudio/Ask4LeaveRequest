import json
from sqlalchemy.orm import Session
from app import main as m
from app.directory import DirectoryConfig
from test_workflow import client, login, submit, approve, signature_payload


def dual_roster():
    data=json.loads((m.ROOT/'config/relationships.example.json').read_text())
    data['counselors'].append({'user_id':'student-a','name':'student-a'})
    for group in data['classes']:group['counselor_ids'].append('student-a')
    return DirectoryConfig.model_validate(data)


def enable_dual():
    with Session(m.engine) as db:m.sync_directory(db,dual_roster())


def test_self_counselor_can_submit_approve_and_revoke(client):
    enable_dual();login(client)
    assert client.get('/api/me').json()['roles']==['student','counselor']
    rid=submit(client)['id']
    assert {r['id'] for r in client.get('/api/requests?view=counselor').json()}=={rid}
    assert client.post('/api/signature',json=signature_payload()).status_code==200
    row=approve(client,rid).json()
    assert row['status']=='approved' and row['approval']['approver']=='student-a'
    assert client.post(f'/api/requests/{rid}/withdraw',json={'role':'student'}).status_code==409
    assert client.post(f'/api/requests/{rid}/withdraw',json={'role':'counselor'}).json()['status']=='revoked'


def test_dual_views_scope_multiple_classes_and_pending_withdrawal(client):
    enable_dual();login(client,'student-b');other=submit(client)['id']
    login(client);own=submit(client)['id']
    assert {r['id'] for r in client.get('/api/requests?view=student').json()}=={own}
    assert {r['id'] for r in client.get('/api/requests?view=counselor').json()}=={own,other}
    assert client.post(f'/api/requests/{other}/withdraw',json={'role':'student'}).status_code==403
    row=client.post(f'/api/requests/{own}/withdraw',json={'role':'student'}).json()
    assert row['status']=='withdrawn' and row['withdrawal']['role']=='student'
    login(client,'student-b')
    assert client.get('/api/requests?view=counselor').status_code==403


def test_dual_student_cannot_self_approve_without_class_assignment(client):
    roster=dual_roster()
    roster.class_counselors=[r for r in roster.class_counselors if r.user_id!='student-a' or r.class_id!=roster.students[0].class_id]
    with Session(m.engine) as db:m.sync_directory(db,roster)
    login(client);rid=submit(client)['id']
    assert client.post(f'/api/requests/{rid}/preview',json={}).status_code==403
    assert client.post(f'/api/requests/{rid}/decision',json={'outcome':'rejected','opinion':'无权'}).status_code==403
    login(client,'counselor-a');assert approve(client,rid).status_code==200
    login(client)
    assert client.post(f'/api/requests/{rid}/withdraw',json={'role':'counselor'}).status_code==403
