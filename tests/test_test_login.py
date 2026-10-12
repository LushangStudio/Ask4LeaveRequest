import io
import json
import secrets
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app import main as m
from test_workflow import payload, signature_payload


@pytest.fixture
def test_client(tmp_path,monkeypatch):
    key=secrets.token_urlsafe(32)
    config=tmp_path/'test-login.json'
    config.write_text(json.dumps({'enabled':True,'secret':key}))
    monkeypatch.setenv('APP_MODE','test')
    monkeypatch.setenv('TEST_LOGIN_CONFIG_PATH',str(config))
    monkeypatch.setenv('RELATIONSHIPS_PATH',str(m.ROOT/'config/relationships.test.json'))
    monkeypatch.delenv('SESSION_COOKIE_PATH',raising=False)
    monkeypatch.delenv('SESSION_COOKIE_SECURE',raising=False)
    monkeypatch.setattr(m,'engine',create_engine('sqlite:///'+str(tmp_path/'test.db'),connect_args={'check_same_thread':False}))
    with TestClient(m.app,follow_redirects=False) as client:
        yield client,key,config


def enter(client,key,uid='test-123'):
    return client.get('/?'+urlencode({'secret':key,'uid':uid}))


def test_url_login_redirect_clean_url_cookie_and_role(test_client):
    c,key,_=test_client
    response=enter(c,key)
    assert response.status_code==303 and response.headers['location']=='/'
    assert key not in str(response.headers) and key not in response.text
    assert response.headers['referrer-policy']=='no-referrer'
    assert response.headers['cache-control']=='no-store'
    cookie=response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    assert c.get('/api/me').json()['id']=='test-123'
    assert c.get('/api/me').json()['profile']['class_id']=='test-class'
    assert c.get('/api/demo/identities').status_code==404
    assert c.post('/api/demo/login',json={'person_id':'test-counselor-1'}).status_code==404
    assert c.get('/api/runtime').json()['uis_login'] is False
    assert enter(c,key,'test-counselor-1').status_code==303
    assert c.get('/api/me').json()['role']=='counselor'


@pytest.mark.parametrize('kind',['wrong_secret','missing_secret','missing_uid','real_uid','empty_suffix','unknown_test','duplicate_secret','duplicate_uid'])
def test_invalid_gate_never_creates_session(test_client,kind):
    c,key,_=test_client
    pairs=[('secret',key),('uid','test-123')]
    if kind=='wrong_secret':pairs[0]=('secret','incorrect')
    elif kind=='missing_secret':pairs=pairs[1:]
    elif kind=='missing_uid':pairs=pairs[:1]
    elif kind=='real_uid':pairs[1]=('uid','01234567890')
    elif kind=='empty_suffix':pairs[1]=('uid','test-')
    elif kind=='unknown_test':pairs[1]=('uid','test-nobody')
    elif kind=='duplicate_secret':pairs.append(('secret',key))
    elif kind=='duplicate_uid':pairs.append(('uid','test-counselor-1'))
    assert c.get('/?'+urlencode(pairs)).status_code==403
    assert c.get('/api/me').status_code==401
    with Session(m.engine) as db:assert db.scalar(select(func.count()).select_from(m.Login))==0


def test_prefix_blocks_existing_non_test_identity(test_client):
    c,key,_=test_client
    with Session(m.engine) as db:
        db.add(m.Person(id='real-user',name='Existing Person',role='student',counselor=None,profile={}))
        db.flush();db.add(m.DirectoryMember(person_id='real-user'));db.commit()
    assert enter(c,key,'real-user').status_code==403


@pytest.mark.parametrize('change',['disabled','rotated'])
def test_disable_or_rotate_revokes_existing_test_session(test_client,change):
    c,key,config=test_client
    assert enter(c,key).status_code==303
    # Restart loading the updated private configuration; old cookies cannot retain access.
    replacement={'enabled':change!='disabled','secret':secrets.token_urlsafe(32) if change=='rotated' else key}
    config.write_text(json.dumps(replacement))
    with TestClient(m.app,follow_redirects=False) as restarted:
        restarted.cookies.update(dict(c.cookies))
        assert restarted.get('/api/me').status_code==401
        assert enter(restarted,key).status_code==403


def test_gate_disabled_by_default_and_does_not_expose_secret(test_client,monkeypatch):
    c,key,_=test_client
    monkeypatch.delenv('TEST_LOGIN_CONFIG_PATH')
    with TestClient(m.app,follow_redirects=False) as disabled:
        assert enter(disabled,key).status_code==403
        assert disabled.get('/api/health').json()=={'status':'ok','mode':'test'}


def test_test_mode_refuses_non_test_roster(test_client,monkeypatch):
    with Session(m.engine) as db:
        state=db.get(m.DirectoryState,1);state.directory=json.loads((m.ROOT/'config/relationships.example.json').read_text());db.commit()
    with pytest.raises(RuntimeError,match='only test-'):
        with TestClient(m.app):pass


def test_invalid_secret_configuration_refuses_startup(test_client):
    _,_,config=test_client
    config.write_text(json.dumps({'enabled':True,'secret':'bad'}))
    with pytest.raises(RuntimeError,match='Invalid private test-login'):
        with TestClient(m.app):pass


def test_asgi_access_log_scope_does_not_contain_url_credentials(test_client):
    _,key,_=test_client
    logged=[]
    async def access_probe(scope,receive,send):
        async def wrapper(message):
            if message['type']=='http.response.start':logged.append(scope['query_string'])
            await send(message)
        await m.app(scope,receive,wrapper)
    with TestClient(access_probe,follow_redirects=False) as c:
        response=c.get('/?'+urlencode({'secret':key,'uid':'test-123','keep':'yes'}))
        assert response.status_code==303
    assert logged==[b'keep=yes']


def test_cookie_base_path_matches_leave_proxy(test_client,monkeypatch):
    c,key,_=test_client
    monkeypatch.setenv('SESSION_COOKIE_PATH','/leave/')
    response=enter(c,key)
    assert response.headers['location']=='/leave/'
    assert 'Path=/leave/' in response.headers['set-cookie']


def test_real_identity_cannot_be_smuggled_into_test_mode_with_demo_cookie(test_client):
    c,_,_=test_client
    from datetime import datetime,timedelta,timezone
    import hashlib
    token=secrets.token_urlsafe(32)
    with Session(m.engine) as db:
        db.add(m.Login(token_hash=hashlib.sha256(token.encode()).hexdigest(),person_id='test-123',expires=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=1)))
        db.commit()
    c.cookies.set('leave_session',token)
    assert c.get('/api/me').status_code==401


def test_full_test_class_workflow_and_student_isolation(test_client):
    c,key,_=test_client
    enter(c,key)
    response=c.post('/api/requests',json=payload())
    assert response.status_code==201,response.text
    rid=response.json()['id']
    enter(c,key,'test-124')
    assert c.get('/api/requests').json()==[] and c.get('/api/requests/'+rid).status_code==404
    enter(c,key,'test-counselor-2')
    assert c.get('/api/requests').json()[0]['id']==rid
    assert c.post('/api/signature',json=signature_payload()).status_code==200
    preview=c.post(f'/api/requests/{rid}/preview',json={'opinion':'同意'}).json()
    response=c.post(f'/api/requests/{rid}/decision',json={'outcome':'approved','opinion':'同意','preview_id':preview['id']})
    assert response.status_code==200,response.text
    result=response.json();assert result['file_status']=='ready'
    enter(c,key,'test-123')
    pdf=PdfReader(io.BytesIO(c.get('/api/documents/'+result['documents'][0]['id']).content))
    text=''.join(page.extract_text() for page in pdf.pages)
    assert '测试学生甲' in text and '测试辅导员乙' in text
    assert c.post('/api/logout').status_code==200
    assert c.get('/api/me').status_code==401
    with Session(m.engine) as db:
        tags=list(db.scalars(select(m.TestLoginSession)))
        assert all(db.get(m.Login,tag.token_hash) for tag in tags)
