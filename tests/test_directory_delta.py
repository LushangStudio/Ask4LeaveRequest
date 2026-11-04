import copy
from sqlalchemy import event, select, func
from sqlalchemy.orm import Session
from app import main as m
from app.directory import class_uuid
from test_class_management import admin_client
from test_workflow import login


def state(c):
    return c.get('/api/admin/directory').json()


def patch(c, snapshot, **changes):
    return c.patch('/api/admin/directory',json={'revision':snapshot['revision'],**changes})


def test_incremental_student_update_does_not_rebuild_tables(admin_client):
    c,_=admin_client;login(c,'admin-only')
    before=state(c)
    student={**before['directory']['students'][0],'major':'增量专业'}
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        statements.append(statement.lower())
    event.listen(m.engine,'before_cursor_execute',capture)
    try:response=patch(c,before,students=[student])
    finally:event.remove(m.engine,'before_cursor_execute',capture)
    assert response.status_code==200,response.text
    expected=copy.deepcopy(before['directory']);expected['students'][0]=student
    assert response.json()['directory']==expected
    assert not any(sql.startswith('delete from directory_') or sql.startswith('delete from class_counselors') for sql in statements)
    assert not any(sql.startswith('insert into directory_students ') or sql.startswith('insert into directory_classes ') for sql in statements)
    with Session(m.engine) as db:
        assert db.get(m.DirectoryStudent,student['user_id']).major=='增量专业'
        assert db.scalar(select(func.count()).select_from(m.DirectoryAudit))==1
    assert patch(c,before,deleted_students=[student['user_id']]).status_code==409
    assert state(c)==response.json()


def test_add_move_delete_classes_and_students_atomically(admin_client):
    c,_=admin_client;login(c,'admin-only')
    before=state(c);cid=class_uuid('delta-class')
    group={'class_id':cid,'name':'增量班级','grade':'2026','department':'管理学院','counselor_ids':['staff-delta']}
    student={'user_id':'delta-student','major':'测试专业','class_id':cid}
    result=patch(c,before,classes=[group],students=[student]);assert result.status_code==200,result.text
    saved=result.json()
    # A referenced class cannot disappear; validation rolls back the whole delta.
    assert patch(c,saved,deleted_classes=[cid]).status_code==422
    assert state(c)==saved
    moved={**student,'class_id':before['directory']['classes'][0]['class_id']}
    result=patch(c,saved,deleted_classes=[cid],students=[moved]);assert result.status_code==200,result.text
    with Session(m.engine) as db:
        assert db.get(m.DirectoryClass,cid) is None
        assert db.get(m.DirectoryStudent,student['user_id']).class_id==moved['class_id']
        assert db.get(m.DirectoryMember,'staff-delta') is None
    result=patch(c,result.json(),deleted_students=[student['user_id']]);assert result.status_code==200
    assert result.json()['directory']==before['directory']


def test_delta_permissions_validation_and_noop(admin_client):
    c,_=admin_client
    assert patch(c,{'revision':'a'*64}).status_code==401
    login(c,'admin-only');before=state(c)
    assert patch(c,before).json()==before
    with Session(m.engine) as db:assert db.scalar(select(func.count()).select_from(m.DirectoryAudit))==0
    student=before['directory']['students'][0]
    assert patch(c,before,students=[student,student]).status_code==422
    assert patch(c,before,students=[student],deleted_students=[student['user_id']]).status_code==422
    assert patch(c,before,deleted_students=['unknown']).status_code==422
    assert patch(c,before,classes=[{**before['directory']['classes'][0],'counselor_ids':[]}]).status_code==422
    assert state(c)==before
    login(c,'student-b');assert patch(c,before,students=[student]).status_code==403


def test_incremental_commit_failure_rolls_back(admin_client,monkeypatch):
    c,_=admin_client;login(c,'admin-only');before=state(c)
    original=Session.commit
    def failure(db):
        if any(isinstance(row,m.DirectoryAudit) for row in db.new):raise RuntimeError('test rollback')
        return original(db)
    monkeypatch.setattr(Session,'commit',failure)
    student={**before['directory']['students'][0],'major':'不应保存'}
    assert patch(c,before,students=[student]).status_code==503
    assert state(c)==before
    with Session(m.engine) as db:assert db.get(m.DirectoryStudent,student['user_id']).major!=student['major']
