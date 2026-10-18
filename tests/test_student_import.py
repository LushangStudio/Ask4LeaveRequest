import copy
import pytest
from sqlalchemy.orm import Session
from app import main as m
from app.directory import DirectoryConfig,class_uuid
from app.student_import import preview_import
from test_class_management import admin_client
from test_workflow import login


def test_batch_import_preview_and_upsert_persist_only_after_confirmation(admin_client):
    c,_=admin_client;login(c,'admin-only')
    state=c.get('/api/admin/directory').json()
    body={'revision':state['revision'],'class_id':class_uuid('class-a'),'text':'学号,专业\n0000123,工商管理\nstudent-b,工商管理'}
    preview=c.post('/api/admin/students/import/preview',json=body).json()
    assert preview['errors']==[] and preview['created']==1 and preview['updated']==1
    assert c.get('/api/admin/directory').json()==state
    saved=c.post('/api/admin/students/import',json=body)
    assert saved.status_code==200,saved.text
    with Session(m.engine) as db:
        assert db.get(m.Person,'0000123').name==''
        assert db.get(m.Person,'student-b').profile['class_id']==class_uuid('class-a')
    # A stale preview cannot overwrite a newer directory.
    assert c.post('/api/admin/students/import',json=body).status_code==409


@pytest.mark.parametrize('text,message',[
    ('a,姓名,class-a,学院,专业,2026','两列'),
    ('a,专业\na,专业','重复'),
    ('a,','必填'),
    ('','至少'),
])
def test_invalid_bulk_rows_are_reported_without_partial_import(admin_client,text,message):
    c,_=admin_client;login(c,'student-a')
    state=c.get('/api/admin/directory').json()
    directory=DirectoryConfig.model_validate(state['directory'])
    result,_=preview_import(text,directory,class_uuid("class-a"))
    assert any(message in e['message'] for e in result['errors'])
    if text:
        body={'text':text,'revision':state['revision'],'class_id':class_uuid('class-a')}
        assert c.post('/api/admin/students/import',json=body).status_code==422
    assert c.get('/api/admin/directory').json()==state


def test_counselor_can_be_imported_as_student_with_self_class(admin_client):
    c,_=admin_client;login(c,'admin-only')
    state=c.get('/api/admin/directory').json()
    result=c.post('/api/admin/students/import',json={'revision':state['revision'],'class_id':class_uuid('class-a'),'text':'counselor-a,工商管理'})
    assert result.status_code==200,result.text
    login(c,'counselor-a')
    assert c.get('/api/me').json()['roles']==['student','counselor']


def test_bulk_endpoints_reject_non_admin(admin_client):
    c,_=admin_client;login(c,'student-a')
    state=c.get('/api/admin/directory').json();login(c,'student-b')
    body={'revision':state['revision'],'class_id':class_uuid('class-a'),'text':'a,专业'}
    for route in ['preview','']:
        assert c.post('/api/admin/students/import'+('/'+route if route else ''),json=body).status_code==403


def test_csv_preserves_leading_zeroes_and_quoted_commas(admin_client):
    c,_=admin_client;login(c,'admin-only')
    state=c.get('/api/admin/directory').json()
    result,_=preview_import('\ufeff000123,"专业,方向"',DirectoryConfig.model_validate(state['directory']),class_uuid('class-a'))
    assert result['errors']==[] and result['students'][0]['user_id']=='000123'
    assert result['students'][0]['major']=='专业,方向'
