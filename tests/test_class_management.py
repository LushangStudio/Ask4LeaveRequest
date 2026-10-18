import copy
import json
import os
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from app import main as m
from test_workflow import login, payload
from test_uis_auth import production,begin,finish


@pytest.fixture
def admin_client(tmp_path,monkeypatch):
    source=tmp_path/'relationships.json'
    source.write_bytes((m.ROOT/'config/relationships.example.json').read_bytes())
    monkeypatch.setenv('APP_MODE','demo')
    monkeypatch.setenv('ADMIN_USER_IDS',' student-a , admin-only ')
    monkeypatch.setenv('RELATIONSHIPS_PATH',str(source))
    monkeypatch.delenv('TEST_RELATIONSHIPS_PATH',raising=False)
    monkeypatch.delenv('TEST_LOGIN_CONFIG_PATH',raising=False)
    monkeypatch.setattr(m,'engine',create_engine('sqlite:///'+str(tmp_path/'admin.db'),connect_args={'check_same_thread':False}))
    with TestClient(m.app) as c:yield c,source


def test_only_configured_admin_can_access_directory(admin_client):
    c,_=admin_client
    assert c.get('/api/admin/directory').status_code==401
    login(c,'student-a');state=c.get('/api/admin/directory').json()
    assert c.get('/api/me').json()['is_admin'] is True
    for uid in ['student-b','counselor-a']:
        login(c,uid)
        assert c.get('/api/me').json()['is_admin'] is False
        assert c.get('/api/admin/directory').status_code==403
        assert c.post('/api/admin/directory',json=state).status_code==403
    login(c,'admin-only')
    assert c.get('/api/me').json()['roles']==[]
    assert c.get('/api/requests').json()==[]
    assert c.get('/api/admin/directory').status_code==200
    assert c.post('/api/requests',json=payload()).status_code==403


def test_create_edit_remove_and_restart_persistence(admin_client):
    c,path=admin_client;login(c,'admin-only')
    state=c.get('/api/admin/directory').json();data=state['directory']
    data['counselors'].append({'user_id':'staff-new'})
    data['classes'].append({'class_id':'new-class','name':'新班级','counselor_ids':['staff-new']})
    data['students'].append({'user_id':'student-new','class_id':'new-class','college':'管理学院','major':'测试专业','grade':'2026'})
    saved=c.post('/api/admin/directory',json=state)
    assert saved.status_code==200,saved.text
    with Session(m.engine) as db:assert db.get(m.DirectoryState,1).directory==data
    path.unlink() # Retired fixture files cannot reset the saved database after restart.
    login(c,'student-new');assert c.get('/api/me').json()['profile']['class_id']=='new-class'
    login(c,'admin-only');edited=saved.json()
    edited['directory']['students'][-1]['major']='更新专业'
    edited['directory']['classes'][-1]['name']='更新班级'
    edited=c.post('/api/admin/directory',json=edited).json()
    removed=copy.deepcopy(edited)
    for key in ['students','classes','counselors']:removed['directory'][key].pop()
    assert c.post('/api/admin/directory',json=removed).status_code==200
    assert c.post('/api/demo/login',json={'person_id':'student-new'}).status_code==400
    with TestClient(m.app) as restarted:
        login(restarted,'admin-only')
        assert restarted.get('/api/admin/directory').json()['directory']==removed['directory']
    with Session(m.engine) as db:
        assert db.scalar(select(func.count()).select_from(m.DirectoryAudit))==3
        assert db.get(m.Person,'student-new') is not None
        assert db.get(m.DirectoryMember,'student-new') is None
    assert not path.exists()


def test_stale_revision_and_invalid_references_preserve_roster(admin_client):
    c,path=admin_client;login(c,'student-a')
    old=c.get('/api/admin/directory').json();changed=copy.deepcopy(old)
    changed['directory']['classes'][0]['name']='修改班级'
    assert c.post('/api/admin/directory',json=changed).status_code==200
    assert c.post('/api/admin/directory',json=old).status_code==409
    before=c.get('/api/admin/directory').json();bad=copy.deepcopy(before)
    bad['directory']['counselors']=[]
    assert c.post('/api/admin/directory',json=bad).status_code==422
    assert c.get('/api/admin/directory').json()==before


def test_save_failure_rolls_back_directory_and_people(admin_client,monkeypatch):
    c,path=admin_client;login(c,'student-a')
    before=c.get('/api/admin/directory').json();state=copy.deepcopy(before)
    state['directory']['students'][0]['major']='不能生效的专业'
    real_commit=Session.commit
    def fail_commit(db):
        if any(isinstance(x,m.DirectoryAudit) for x in db.new):raise RuntimeError('simulated DB commit failure')
        return real_commit(db)
    monkeypatch.setattr(Session,'commit',fail_commit)
    assert c.post('/api/admin/directory',json=state).status_code==503
    assert c.get('/api/admin/directory').json()==before
    with Session(m.engine) as db:
        assert db.get(m.Person,'student-a').name==''
        assert db.scalar(select(func.count()).select_from(m.DirectoryAudit))==0


def test_retired_json_changes_are_ignored(admin_client):
    c,path=admin_client;login(c,'admin-only')
    state=c.get('/api/admin/directory').json()
    path.write_bytes(path.read_bytes()+b'\n')
    assert c.post('/api/admin/directory',json=state).status_code==200


def test_configured_admin_uis_login_needs_no_student_class(production):
    c,control,monkeypatch=production
    monkeypatch.setenv('ADMIN_USER_IDS','admin-uis-user, staff-1')
    control['user']['user_id']='admin-uis-user';control['user']['user_name']='测试管理员'
    with TestClient(m.app,base_url='https://app.example',follow_redirects=False) as admin:
        assert finish(admin,begin(admin)).status_code==303
        me=admin.get('/api/me').json()
        assert me['is_admin'] is True and me['role']=='admin' and me['name']=='测试管理员'
        assert admin.get('/api/admin/directory').status_code==200


def test_management_page_assets_use_parent_base(admin_client):
    c,_=admin_client
    html=c.get('/class-management/').text
    assert '<base href="../">' in html
    assert 'student-a' not in html


def test_legacy_import_is_idempotent_and_refuses_overwriting_online_data(admin_client):
    c,path=admin_client;login(c,'admin-only')
    args=[sys.executable,'-m','app.import_directory',str(path)]
    env={**os.environ,'DATABASE_URL':str(m.engine.url)}
    imported=subprocess.run(args,env=env,capture_output=True,text=True)
    assert imported.returncode==0,imported.stderr
    before=c.get('/api/admin/directory').json()
    data=json.loads(path.read_text());data['classes'][0]['name']='旧文件试图覆盖在线名单'
    path.write_text(json.dumps(data))
    refused=subprocess.run(args,env=env,capture_output=True,text=True)
    assert refused.returncode==1 and '拒绝覆盖' in refused.stderr
    assert c.get('/api/admin/directory').json()==before


def test_production_ignores_relationship_files_after_restart(production,tmp_path):
    c,control,monkeypatch=production
    broken=tmp_path/'obsolete.json';broken.write_text('{broken')
    monkeypatch.setenv('RELATIONSHIPS_PATH',str(broken))
    monkeypatch.setenv('TEST_RELATIONSHIPS_PATH',str(tmp_path/'missing.json'))
    with TestClient(m.app,base_url='https://app.example',follow_redirects=False) as restarted:
        assert finish(restarted,begin(restarted)).status_code==303
        assert restarted.get('/api/me').json()['id']=='01234567890'


def test_restart_scrubs_legacy_student_names_without_changing_requests(admin_client):
    from test_workflow import submit
    c,_=admin_client
    login(c,'student-a')
    rid=submit(c)['id']
    with Session(m.engine) as db:
        state=db.get(m.DirectoryState,1)
        legacy=copy.deepcopy(state.directory)
        legacy['students'][0]['name']='旧名册姓名'
        state.directory=legacy
        state.digest=m.directory_digest(legacy)
        db.get(m.Person,'student-a').name='旧名册姓名'
        legacy['counselors'][0]['name']='旧辅导员姓名'
        state.directory=copy.deepcopy(legacy)
        state.digest=m.directory_digest(legacy)
        db.get(m.Person,'counselor-a').name='旧辅导员姓名'
        db.add(m.Person(id='retired-student',name='停用学生姓名',role='student',profile={}))
        db.get(m.Request,rid).snapshot={**db.get(m.Request,rid).snapshot,'name':'历史申请姓名'}
        db.commit()
    with TestClient(m.app) as restarted:
        login(restarted,'admin-only')
        data=restarted.get('/api/admin/directory').json()
        assert all('name' not in s for s in data['directory']['students'])
        assert data['revision']==m.directory_digest(data['directory'])
    with Session(m.engine) as db:
        assert db.get(m.Person,'student-a').name==''
        assert db.get(m.Person,'retired-student').name==''
        assert db.get(m.Person,'counselor-a').name==''
        assert all('name' not in c for c in db.get(m.DirectoryState,1).directory['counselors'])
        assert db.get(m.Request,rid).snapshot['name']=='历史申请姓名'
