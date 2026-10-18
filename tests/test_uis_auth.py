import base64
import hashlib
import json
import secrets
from datetime import datetime,timedelta,timezone
from urllib.parse import parse_qs,urlparse,urlencode

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session

from app import main as m
from app.uis import UISOAuthClient,UISSettings


@pytest.fixture
def production(tmp_path,monkeypatch):
    roster={'version':1,'counselors':[{'user_id':'staff-1','name':'辅导员甲'}],
            'classes':[{'class_id':'class-1','name':'本科测试班','counselor_ids':['staff-1']}],
            'students':[{'user_id':'01234567890','name':'学生甲','class_id':'class-1','college':'管理学院','major':'工商管理','grade':'2026'}]}
    source=tmp_path/'relationships.json';source.write_text(json.dumps(roster))
    monkeypatch.setenv('APP_MODE','production')
    monkeypatch.setenv('RELATIONSHIPS_PATH',str(source))
    monkeypatch.delenv('TEST_RELATIONSHIPS_PATH',raising=False)
    monkeypatch.delenv('TEST_LOGIN_CONFIG_PATH',raising=False)
    monkeypatch.setenv('UIS_OAUTH_CLIENT_ID','uis-client')
    monkeypatch.setenv('UIS_OAUTH_CLIENT_SECRET','uis-client-secret')
    monkeypatch.setenv('UIS_OAUTH_REDIRECT_URI','https://app.example/api/auth/callback')
    monkeypatch.setenv('AUTH_FRONTEND_URL','https://app.example/')
    monkeypatch.setenv('PUBLIC_ORIGIN','https://app.example')
    monkeypatch.setenv('SESSION_COOKIE_PATH','/')
    monkeypatch.setattr(m,'engine',create_engine('sqlite:///'+str(tmp_path/'auth.db'),connect_args={'check_same_thread':False}))
    m.Base.metadata.create_all(m.engine)
    with Session(m.engine) as db:
        db.add(m.DirectoryState(id=1,directory=roster,digest=m.directory_digest(roster),updated=datetime.now(timezone.utc).isoformat()));db.commit()
    response_user={'user_id':'01234567890','user_name':'学生甲','user_type':'本专科生','sessionId':'uis-session'}
    control={'user':response_user,'token':{'access_token':'access-token','token_type':'Bearer'},'calls':[]}
    def handler(request):
        control['calls'].append(request)
        if request.method=='POST':return httpx.Response(200,json=control['token'])
        return httpx.Response(200,json=control['user'])
    def provider():return UISOAuthClient(m.app.state.uis_settings,httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    m.app.dependency_overrides[m.get_uis_oauth_client]=provider
    try:
        with TestClient(m.app,base_url='https://app.example',follow_redirects=False) as c:yield c,control,monkeypatch
    finally:m.app.dependency_overrides.pop(m.get_uis_oauth_client,None)


def begin(c):
    r=c.get('/api/auth/login');assert r.status_code==302,r.text
    query=parse_qs(urlparse(r.headers['location']).query)
    assert query['response_type']==['code'] and query['client_id']==['uis-client']
    assert query['redirect_uri']==['https://app.example/api/auth/callback']
    assert 'httponly' in r.headers['set-cookie'].lower() and 'secure' in r.headers['set-cookie'].lower()
    assert 'samesite=lax' in r.headers['set-cookie'].lower()
    return query['state'][0]


def finish(c,state):return c.get('/api/auth/callback',params={'code':'authorization-code','state':state})


@pytest.mark.parametrize('user_type',['本专科生','研究生','教职工','其他身份'])
def test_uis_has_no_student_type_restriction(production,user_type):
    c,control,_=production
    control['user']['user_type']=user_type
    response=finish(c,begin(c))
    assert response.status_code==303 and response.headers['location']=='https://app.example/'
    me=c.get('/api/me').json()
    assert me['id']=='01234567890' and me['role']=='student' and me['auth_provider']=='uis'
    assert me['user_type']==user_type
    assert c.post('/api/demo/login',json={'person_id':'staff-1'}).status_code==404
    assert c.get('/api/runtime').json()['uis_login'] is True
    token_request,user_request=control['calls']
    assert token_request.headers['Authorization']=='Basic '+base64.b64encode(b'uis-client:uis-client-secret').decode()
    assert token_request.content==b'grant_type=authorization_code&code=authorization-code'
    assert user_request.headers['Authorization']=='Bearer access-token'
    with Session(m.engine) as db:assert db.scalar(select(func.count()).select_from(m.UISLoginSession))==1


def test_counselor_role_comes_from_operator_roster(production):
    c,control,_=production
    control['user'].update(user_id='staff-1',user_name='辅导员甲',user_type='教职工')
    assert finish(c,begin(c)).status_code==303
    assert c.get('/api/me').json()['role']=='counselor'


@pytest.mark.parametrize('case',['wrong','missing','expired','replayed'])
def test_state_validation_and_replay_prevent_provider_calls(production,case):
    c,control,_=production
    state=begin(c)
    if case=='wrong':state='wrong-state'
    elif case=='missing':c.cookies.delete('leave_oauth_state')
    elif case=='expired':
        with Session(m.engine) as db:
            db.get(m.OAuthState,hashlib.sha256(state.encode()).hexdigest()).expires=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1);db.commit()
    elif case=='replayed':
        assert finish(c,state).status_code==303
        c.cookies.set('leave_oauth_state',state,domain='app.example',path='/')
        control['calls'].clear()
    assert finish(c,state).status_code==400
    assert control['calls']==[]


@pytest.mark.parametrize('user_id',[None,'','   '])
def test_upstream_empty_id_is_rejected(production,user_id):
    c,control,_=production;control['user']['user_id']=user_id
    response=finish(c,begin(c))
    assert response.status_code==502 and response.json()['detail']=='UIS身份认证失败'
    assert c.get('/api/me').status_code==401


def test_unknown_uid_does_not_get_a_role(production):
    c,control,_=production;control['user']['user_id']='unconfigured'
    assert finish(c,begin(c)).status_code==403
    assert c.get('/api/me').status_code==401


@pytest.mark.parametrize('operation',['token','user'])
def test_provider_error_does_not_leak_credentials(production,operation):
    c,control,_=production
    control['token' if operation=='token' else 'user']={'errcode':'invalid_grant','errmsg':'private-provider-message'}
    response=finish(c,begin(c))
    assert response.status_code==502
    assert 'private-provider-message' not in response.text and 'uis-client-secret' not in response.text


def test_real_login_and_global_logout(production):
    c,_,_=production;assert finish(c,begin(c)).status_code==303
    response=c.post('/api/auth/logout',headers={'Origin':'https://app.example'})
    assert response.status_code==303
    query=parse_qs(urlparse(response.headers['location']).query)
    assert query=={'redirectToLogin':['true'],'redirectToUrl':['https://app.example/']}
    assert c.get('/api/me').status_code==401


def test_production_rejects_ordinary_demo_session(production):
    c,_,_=production
    token=secrets.token_urlsafe(32)
    with Session(m.engine) as db:
        db.add(m.Login(token_hash=hashlib.sha256(token.encode()).hexdigest(),person_id='01234567890',expires=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=1)));db.commit()
    c.cookies.set('leave_session',token,domain='app.example',path='/')
    assert c.get('/api/me').status_code==401


def test_uis_and_test_gate_coexist_and_restart_requires_uis_relogin(production,tmp_path):
    c,_,monkeypatch=production
    key=secrets.token_urlsafe(32)
    config=tmp_path/'gate.json';config.write_text(json.dumps({'enabled':True,'secret':key}))
    monkeypatch.setenv('TEST_LOGIN_CONFIG_PATH',str(config))
    with Session(m.engine) as db:
        state=db.get(m.DirectoryState,1);data=dict(state.directory)
        test=json.loads((m.ROOT/'config/relationships.test.json').read_text())
        for field in ['students','counselors','classes']:data[field]=data[field]+test[field]
        state.directory=data;state.digest=m.directory_digest(data);db.commit()
    with TestClient(m.app,base_url='https://app.example',follow_redirects=False) as real:
        assert finish(real,begin(real)).status_code==303
        test=TestClient(m.app,base_url='https://app.example',follow_redirects=False)
        assert test.get('/?'+urlencode({'secret':key,'uid':'test-123'})).status_code==303
        assert test.get('/api/me').json()['auth_provider']=='test'
        assert test.post('/api/auth/logout').status_code==403
        config.write_text(json.dumps({'enabled':False,'secret':key}))
        with TestClient(m.app,base_url='https://app.example',follow_redirects=False) as restarted:
            restarted.cookies.update(dict(real.cookies))
            assert restarted.get('/api/me').status_code==401
            assert finish(restarted,begin(restarted)).status_code==303
            assert restarted.get('/api/me').status_code==200
            assert restarted.get('/?'+urlencode({'secret':key,'uid':'test-123'})).status_code==403
            restarted.cookies.clear()
            restarted.cookies.update(test.cookies)
            assert restarted.get('/api/me').status_code==401


def test_callback_access_log_does_not_contain_code_or_state(production):
    c,control,_=production;state=begin(c);logs=[]
    async def outer(scope,receive,send):
        async def respond(message):
            if message['type']=='http.response.start':logs.append(scope['query_string'])
            await send(message)
        await m.app(scope,receive,respond)
    probe=TestClient(outer,base_url='https://app.example',follow_redirects=False);probe.cookies.update(dict(c.cookies))
    assert finish(probe,state).status_code==303
    assert logs==[b'']


def test_production_refuses_missing_uis_configuration(production):
    _,_,monkeypatch=production;monkeypatch.delenv('UIS_OAUTH_CLIENT_SECRET')
    with pytest.raises(RuntimeError,match='not configured'):
        with TestClient(m.app):pass


def test_shared_callback_has_routing_namespace_and_separate_cookie_path(production):
    c,control,monkeypatch=production
    monkeypatch.setenv('SESSION_COOKIE_PATH','/leave/')
    monkeypatch.setenv('UIS_STATE_COOKIE_PATH','/api/auth/')
    monkeypatch.setenv('AUTH_FRONTEND_URL','https://app.example/leave/')
    # The request is forwarded from /leave/api/auth/login; callback is the existing public path.
    response=c.get('/api/auth/login')
    assert 'Path=/api/auth/' in response.headers['set-cookie']
    state=parse_qs(urlparse(response.headers['location']).query)['state'][0]
    assert state.startswith('ask4leave.')
    result=finish(c,state)
    assert result.status_code==303
    cookies=result.headers.get_list('set-cookie')
    assert any('leave_session=' in item and 'Path=/leave/' in item for item in cookies)
    assert any('leave_oauth_state=' in item and 'Path=/api/auth/' in item and 'Max-Age=0' in item for item in cookies)


def test_forged_shared_callback_prefix_cannot_authenticate(production):
    c,control,_=production
    begin(c)
    result=finish(c,'ask4leave.'+secrets.token_urlsafe(32))
    assert result.status_code==400 and control['calls']==[]


def test_student_name_is_uis_only_and_never_written_to_roster(production):
    from test_workflow import payload
    c,control,_=production
    control['user']['user_name']='UIS实名同学'
    assert finish(c,begin(c)).status_code==303
    assert c.get('/api/me').json()['name']=='UIS实名同学'
    response=c.post('/api/requests',json=payload())
    assert response.status_code==201,response.text
    with Session(m.engine) as db:
        state=db.get(m.DirectoryState,1)
        assert all('name' not in student for student in state.directory['students'])
        assert state.digest==m.directory_digest(state.directory)
        assert db.get(m.Person,'01234567890').name==''
        assert db.get(m.Request,response.json()['id']).snapshot['name']=='UIS实名同学'
    # No silent fallback to a blank/name from the roster after cache loss/restart.
    m.app.state.uis_names.clear()
    assert c.get('/api/me').status_code==401
    control['user']['user_name']='UIS更新姓名'
    assert finish(c,begin(c)).status_code==303
    assert c.get('/api/me').json()['name']=='UIS更新姓名'
    with Session(m.engine) as db:
        assert db.get(m.Person,'01234567890').name==''
        assert db.get(m.Request,response.json()['id']).snapshot['name']=='UIS实名同学'
    c.post('/api/logout')
    assert not m.app.state.uis_names


def test_counselor_uis_name_is_snapshotted_in_approval_and_pdf_only(production):
    import io
    from pypdf import PdfReader
    from test_workflow import payload,signature_payload,approve
    c,control,_=production
    assert finish(c,begin(c)).status_code==303
    response=c.post('/api/requests',json=payload())
    assert response.status_code==201
    rid=response.json()['id']
    control['user'].update(user_id='staff-1',user_name='UIS辅导员实名',user_type='教职工')
    assert finish(c,begin(c)).status_code==303
    assert c.get('/api/me').json()['name']=='UIS辅导员实名'
    assert c.post('/api/signature',json=signature_payload()).status_code==200
    result=approve(c,rid)
    assert result.status_code==200,result.text
    row=result.json()
    assert row['approval']['approver']=='UIS辅导员实名'
    import time
    deadline=time.monotonic()+10
    while not row['documents'] and time.monotonic()<deadline:
        time.sleep(0.05)
        row=c.get('/api/requests/'+rid).json()
    assert row['file_status']=='ready',row
    pdf=c.get('/api/documents/'+row['documents'][0]['id'])
    assert 'UIS辅导员实名' in ''.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    with Session(m.engine) as db:
        assert db.get(m.Person,'staff-1').name==''
        assert all('name' not in p for p in db.get(m.DirectoryState,1).directory['counselors'])
    control['user']['user_name']='UIS更新后的辅导员'
    assert finish(c,begin(c)).status_code==303
    assert c.get('/api/me').json()['name']=='UIS更新后的辅导员'
    assert c.get('/api/requests/'+rid).json()['approval']['approver']=='UIS辅导员实名'
