import copy
import json
from uuid import UUID
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import main as m
from app.directory import DirectoryConfig,class_uuid
from test_class_management import admin_client
from test_workflow import client,login,submit


def test_v1_migration_is_stable_and_normalizes_fields():
    old=json.loads((m.ROOT/'config/relationships.example.json').read_text())
    new=DirectoryConfig.model_validate(old).model_dump()
    assert new==DirectoryConfig.model_validate(old).model_dump()
    assert new==DirectoryConfig.model_validate(new).model_dump()
    assert set(new)=={'version','classes','class_counselors','students'}
    for group in new['classes']:
        assert str(UUID(group['class_id']))==group['class_id']
        assert set(group)=={'class_id','name','grade','department'}
    for student in new['students']:
        assert set(student)=={'user_id','major','class_id'}


def test_ambiguous_legacy_class_refuses_to_guess():
    old=json.loads((m.ROOT/'config/relationships.example.json').read_text())
    duplicate={**old['students'][0],'user_id':'different-student','grade':'2099'}
    old['students'].append(duplicate)
    with pytest.raises(ValidationError,match='不一致'):DirectoryConfig.model_validate(old)


def test_class_changes_flow_to_new_requests_only(admin_client):
    c,_=admin_client;login(c,'student-a')
    old=submit(c)
    state=c.get('/api/admin/directory').json()
    group=state['directory']['classes'][0]
    group.update(name='新班名',grade='2027',department='新院系')
    assert c.post('/api/admin/directory',json=state).status_code==200
    profile=c.get('/api/me').json()['profile']
    assert (profile['college'],profile['grade'],profile['class_name'])==('新院系','2027','新班名')
    with Session(m.engine) as db:
        stored=db.get(m.DirectoryClass,group['class_id'])
        assert stored.department=='新院系'
        assert db.get(m.DirectoryStudent,'student-a').class_id==group['class_id']
        assert db.get(m.Request,old['id']).snapshot['college']!='新院系'


def test_import_requires_selected_existing_class(admin_client):
    c,_=admin_client;login(c,'admin-only')
    state=c.get('/api/admin/directory').json()
    body={'revision':state['revision'],'text':'0001,专业'}
    assert c.post('/api/admin/students/import',json=body).status_code==422
    body['class_id']=class_uuid('nonexistent')
    assert c.post('/api/admin/students/import',json=body).status_code==422
    assert c.get('/api/admin/directory').json()==state


def test_failed_save_rolls_back_normalized_tables(admin_client,monkeypatch):
    c,_=admin_client;login(c,'admin-only')
    state=c.get('/api/admin/directory').json()
    group=state['directory']['classes'][0]
    old=group['department'];group['department']='不能保存'
    real=Session.commit
    def fail(db):
        if any(isinstance(x,m.DirectoryAudit) for x in db.new):raise RuntimeError('test rollback')
        return real(db)
    monkeypatch.setattr(Session,'commit',fail)
    assert c.post('/api/admin/directory',json=state).status_code==503
    with Session(m.engine) as db:
        assert db.get(m.DirectoryClass,group['class_id']).department==old
        assert db.get(m.DirectoryStudent,'student-a') is not None
        assert list(db.scalars(select(m.ClassCounselor)))


def test_relation_removal_revokes_counselor_membership(admin_client):
    c,_=admin_client;login(c,'admin-only')
    state=c.get('/api/admin/directory').json()
    state['directory']['class_counselors']=[r for r in state['directory']['class_counselors'] if r['user_id']!='counselor-c']
    assert c.post('/api/admin/directory',json=state).status_code==200
    assert c.post('/api/demo/login',json={'person_id':'counselor-c'}).status_code==400


def test_normalized_tables_sync_on_database_backend(client):
    with Session(m.engine) as db:
        roster=DirectoryConfig.model_validate(db.get(m.DirectoryState,1).directory)
        m.sync_directory(db,roster)
        assert len(list(db.scalars(select(m.DirectoryClass))))==len(roster.classes)
        assert len(list(db.scalars(select(m.ClassCounselor))))==len(roster.class_counselors)
        assert len(list(db.scalars(select(m.DirectoryStudent))))==len(roster.students)
        assert db.get(m.DirectoryStudent,'student-a').class_id==class_uuid('class-a')
