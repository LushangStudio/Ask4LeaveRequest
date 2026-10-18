import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session
from app import main as m
from test_workflow import client, login, submit, approve
from test_uis_auth import production, begin, finish


@pytest.mark.parametrize('headers', [
    {'Origin':'https://attacker.example'},
    {'Origin':'null'},
    {'Sec-Fetch-Site':'cross-site'},
])
def test_csrf_rejected_without_state_change(client, headers):
    login(client)
    rid=submit(client)['id']
    assert client.post(f'/api/requests/{rid}/withdraw',json={},headers=headers).status_code==403
    assert client.get('/api/requests/'+rid).json()['status']=='pending'
    assert client.post('/api/logout',headers=headers).status_code==403
    assert client.get('/api/me').status_code==200


def test_secure_session_expiry_and_private_headers(production):
    c,_,_=production
    response=finish(c,begin(c))
    cookie=next(value for value in response.headers.get_list('set-cookie') if value.startswith('leave_session='))
    for attribute in ('Secure','HttpOnly','SameSite=strict','Max-Age='):
        assert attribute.lower() in cookie.lower()
    response=c.get('/api/me')
    assert response.headers['cache-control']=='no-store'
    assert response.headers['referrer-policy']=='no-referrer'
    token=c.cookies.get('leave_session')
    with Session(m.engine) as db:
        db.get(m.Login,hashlib.sha256(token.encode()).hexdigest()).expires=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1)
        db.commit()
    for url in ('/api/me','/api/requests','/api/admin/directory','/api/signature/image'):
        assert c.get(url).status_code==401


def test_all_request_and_file_operations_isolate_unrelated_people(client):
    login(client);rid=submit(client)['id']
    login(client,'counselor-a')
    preview=client.post(f'/api/requests/{rid}/preview',json={}).json()
    for person in ('student-b','counselor-b'):
        login(client,person)
        assert client.get('/api/requests/'+rid).status_code==404
        for operation,body in [('preview',{}),('retry',{}),('withdraw',{}),('decision',{'outcome':'rejected','opinion':'x'})]:
            expected=403 if person=='student-b' and operation=='preview' else 404
            assert client.post(f'/api/requests/{rid}/{operation}',json=body).status_code==expected
        assert client.get(f"/api/previews/{preview['id']}/0").status_code in {403,404}
        assert client.get('/api/admin/directory').status_code==403
        for route in ('/api/admin/students/import/preview','/api/admin/students/import'):
            assert client.post(route,json={'text':'x','revision':'0'*64,'class_id':'invalid'}).status_code==403
    login(client,'counselor-a');row=approve(client,rid).json()
    for person in ('student-b','counselor-b'):
        login(client,person)
        for doc in row['documents']:
            assert client.get('/api/documents/'+doc['id']).status_code==404
    client.post('/api/logout')
    assert client.get('/api/documents/'+row['documents'][0]['id']).status_code==401


def test_health_fails_closed_on_database_error(client, monkeypatch):
    assert client.get('/api/health').status_code==200
    def broken(*args,**kwargs):raise RuntimeError('private database connection detail')
    monkeypatch.setattr(Session,'execute',broken)
    response=client.get('/api/health')
    assert response.status_code==503
    assert 'private' not in response.text
