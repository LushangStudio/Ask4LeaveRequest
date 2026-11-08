import pytest
from sqlalchemy import event
from app import main as m
from app.directory import class_uuid
from test_class_management import admin_client
from directory_helpers import read_directory
from test_workflow import login

@pytest.fixture
def many_rows(admin_client):
    c,_=admin_client;login(c,'admin-only')
    state=read_directory(c);data=state['directory'];base=data['classes'][0]['class_id']
    for n in range(103):
        cid=class_uuid(f'page-{n}')
        data['classes'].append(dict(class_id=cid,name=f'分页班级{n:03}',grade='2026',department='测试院系'))
        data['class_counselors'].append(dict(class_id=cid,user_id='staff-page'))
    for n in range(630):
        data['students'].append(dict(user_id=f'page-{n:04}',major=f'专业{n%63:02}',class_id=base))
    assert c.post('/api/admin/directory',json=state).status_code==200
    return c,base


def test_only_requested_page_is_returned_and_queried(many_rows):
    c,_=many_rows
    seen=set();statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):statements.append(statement.lower())
    event.listen(m.engine,'before_cursor_execute',capture)
    try:
        for page in range(1,14):
            result=c.get('/api/admin/directory',params={'view':'students','page':page}).json()
            assert result['total']==632 and result['pages']==13
            assert len(result['directory']['students'])==(32 if page==13 else 50)
            assert result['directory']['classes']==[] and result['directory']['class_counselors']==[]
            ids={s['user_id'] for s in result['directory']['students']}
            assert not seen&ids;seen|=ids
            assert all(s['class_label'] for s in result['directory']['students'])
    finally:event.remove(m.engine,'before_cursor_execute',capture)
    assert len(seen)==632
    assert any('limit' in sql and 'directory_students' in sql for sql in statements)
    assert not any('directory_state.directory' in sql for sql in statements)
    result=c.get('/api/admin/directory',params={'view':'classes','page':3}).json()
    assert len(result['directory']['classes'])==5 and result['total']==105
    assert result['directory']['students']==[]
    ids={row['class_id'] for row in result['directory']['classes']}
    assert all(row['class_id'] in ids for row in result['directory']['class_counselors'])


def test_filters_page_clamp_and_bounded_selectors(many_rows):
    c,cid=many_rows
    result=c.get('/api/admin/directory',params={'view':'students','class_id':cid,'major':'专业01','page':999}).json()
    assert result['page']==1 and result['total']==10
    assert all(s['class_id']==cid and s['major']=='专业01' for s in result['directory']['students'])
    majors=c.get('/api/admin/majors',params={'page':2,'q':'专业','class_id':cid}).json()
    assert majors['total']==63 and len(majors['items'])==13
    for q in ['%','_']:
        assert c.get('/api/admin/directory',params={'q':q}).json()['total']==0
    assert c.get('/api/admin/directory',params={'page':0}).status_code==422
    assert c.get('/api/admin/directory',params={'view':'invalid'}).status_code==422
    login(c,'student-b')
    assert c.get('/api/admin/directory').status_code==403
    assert c.get('/api/admin/majors').status_code==403


def test_saves_and_bulk_import_never_echo_full_roster(many_rows):
    c,cid=many_rows
    result=c.get('/api/admin/directory',params={'view':'students'}).json()
    row=result['directory']['students'][0]
    change={k:row[k] for k in ['user_id','major','class_id']};change['major']='更新专业'
    saved=c.patch('/api/admin/directory',json={'revision':result['revision'],'students':[change]})
    assert saved.status_code==200 and set(saved.json())=={'revision'}
    body={'revision':saved.json()['revision'],'class_id':cid,'text':'\n'.join(f'import-{n:03},导入专业' for n in range(120))}
    preview=c.post('/api/admin/students/import/preview',json=body).json()
    assert preview['total']==120 and len(preview['students'])==50
    imported=c.post('/api/admin/students/import',json=body).json()
    assert set(imported)=={'revision','created','updated'}
    assert imported['created']==120
