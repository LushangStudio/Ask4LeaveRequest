import base64
import copy
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfReader
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app import main as m
from app.directory import DirectoryConfig, read_directory, read_directories
from test_workflow import client, login, submit, payload, approve, signature_payload


def roster_payload():
    return json.loads((m.ROOT/'config/relationships.example.json').read_text())


@pytest.mark.parametrize('invalid', ['duplicate_student','duplicate_class','duplicate_counselor','unknown_class','unknown_counselor','no_counselor','blank_id','role_collision','multiple_classes','unknown_field'])
def test_operator_config_rejects_invalid_relationships(invalid):
    data=roster_payload()
    if invalid=='duplicate_student': data['students'].append(copy.deepcopy(data['students'][0]))
    elif invalid=='duplicate_class':data['classes'].append(copy.deepcopy(data['classes'][0]))
    elif invalid=='duplicate_counselor':data['classes'][0]['counselor_ids'].append('counselor-a')
    elif invalid=='unknown_class':data['students'][0]['class_id']='missing'
    elif invalid=='unknown_counselor':data['classes'][0]['counselor_ids']=['missing']
    elif invalid=='no_counselor':data['classes'][0]['counselor_ids']=[]
    elif invalid=='blank_id':data['students'][0]['user_id']='   '
    elif invalid=='role_collision':data['students'][0]['user_id']='counselor-a'
    elif invalid=='multiple_classes':data['students'][0]['class_id']=['class-a','class-b']
    elif invalid=='unknown_field':data['students'][0]['counselor_id']='counselor-a'
    with pytest.raises(ValidationError):DirectoryConfig.model_validate(data)


def test_config_rejects_duplicate_json_keys(tmp_path):
    source=tmp_path/'roster.json';source.write_text('{"version":1,"version":1}')
    with pytest.raises(ValueError,match='重复'):read_directory(str(source))


def test_empty_production_roster_can_merge_test_class():
    roster=read_directories(str(m.ROOT/'config/relationships.production.example.json'),
                            str(m.ROOT/'config/relationships.test.json'))
    assert len(roster.classes)==1 and len(roster.counselors)==2
    assert {p.user_id for p in roster.students}=={'test-123','test-124','test-125'}


def test_secondary_test_roster_rejects_real_namespace():
    with pytest.raises(ValueError,match='test-'):
        read_directories(str(m.ROOT/'config/relationships.production.example.json'),
                         str(m.ROOT/'config/relationships.example.json'))


def test_merged_rosters_reject_duplicate_identities():
    with pytest.raises(ValidationError,match='重复'):
        read_directories(str(m.ROOT/'config/relationships.test.json'),
                         str(m.ROOT/'config/relationships.test.json'))


def test_multiclass_counselor_and_one_final_decision(client):
    login(client);first=submit(client)
    login(client,'student-b');second=submit(client)
    login(client,'counselor-c')
    assert {r['id'] for r in client.get('/api/requests').json()}=={first['id'],second['id']}
    assert approve(client,first['id']).status_code==200
    login(client,'counselor-a')
    assert {r['id'] for r in client.get('/api/requests').json()}=={first['id']}
    assert approve(client,first['id']).status_code==409
    assert approve(client,second['id']).status_code==404
    login(client)
    approved=client.get('/api/requests/'+first['id']).json()
    assert approved['approval']['approver']=='演示辅导员丙'
    text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(client.get('/api/documents/'+approved['documents'][0]['id']).content)).pages)
    assert '演示辅导员丙' in text and '工商管理一班' in text


@pytest.mark.parametrize('layout,count',[('combined',1),('separate',2)])
def test_preview_requires_signature_has_watermark_and_no_side_effects(client,layout,count):
    login(client);rid=submit(client,payload(layout))['id']
    assert client.post(f'/api/requests/{rid}/preview',json={}).status_code==403
    assert client.post('/api/signature',json=signature_payload()).status_code==403
    login(client,'counselor-a',with_signature=False)
    assert client.post(f'/api/requests/{rid}/preview',json={}).status_code==409
    assert client.post(f'/api/requests/{rid}/decision',json={'outcome':'approved'}).status_code==409
    assert client.post('/api/signature',json=signature_payload()).status_code==200
    assert client.post(f'/api/requests/{rid}/decision',json={'outcome':'approved'}).status_code==409
    preview=client.post(f'/api/requests/{rid}/preview',json={'opinion':'已核对'}).json()
    assert preview['count']==count
    assert preview['watermark']=='演示学生甲（请假人）-2026-10-01-3天'
    for index in range(count):
        response=client.get(f"/api/previews/{preview['id']}/{index}")
        assert response.status_code==200
        pdf=PdfReader(io.BytesIO(response.content))
        text=''.join(page.extract_text() for page in pdf.pages)
        assert '审批前预览' in text and '辅导员签字' in text
        assert sum(len(page.images) for page in pdf.pages)==1
        with Session(m.engine) as db:
            stored=db.get(m.ApprovalPreview,preview['id'])
            assert stored.watermark==preview['watermark']
            embedded=[image.image.convert('RGB') for page in pdf.pages for image in page.images][0]
            assert embedded.tobytes()==Image.open(io.BytesIO(stored.signature_content)).convert('RGB').tobytes()
    assert client.get(f"/api/previews/{preview['id']}/{count}").status_code==404
    row=client.get('/api/requests/'+rid).json()
    assert row['status']=='pending' and row['approval'] is None and row['documents']==[]
    with Session(m.engine) as db:
        assert db.scalar(select(func.count()).select_from(m.ApprovalSignature))==0
    login(client,'counselor-b')
    assert client.get(f"/api/previews/{preview['id']}/0").status_code==404
    assert client.post(f'/api/requests/{rid}/decision',json={'outcome':'approved','opinion':'已核对','preview_id':preview['id']}).status_code==404
    login(client)
    assert client.get('/api/signature/image').status_code==403


@pytest.mark.parametrize('change',['opinion','signature','expiry','other_request','other_reviewer'])
def test_changed_or_expired_preview_cannot_approve(client,change):
    login(client);rid=submit(client)['id'];second=submit(client)['id']
    login(client,'counselor-a')
    preview=client.post(f'/api/requests/{rid}/preview',json={'opinion':'同意'}).json()
    body={'outcome':'approved','opinion':'同意','preview_id':preview['id']}
    if change=='opinion':body['opinion']='新的意见'
    elif change=='signature':client.post('/api/signature',json=signature_payload())
    elif change=='expiry':
        with Session(m.engine) as db:
            db.get(m.ApprovalPreview,preview['id']).expires=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1);db.commit()
    elif change=='other_request':rid=second
    elif change=='other_reviewer':login(client,'counselor-c')
    assert client.post(f'/api/requests/{rid}/decision',json=body).status_code==409
    assert client.get('/api/requests/'+rid).json()['status']=='pending'


def test_signature_snapshot_survives_replacement_and_retry(client,monkeypatch):
    login(client);rid=submit(client)['id'];login(client,'counselor-a')
    before=client.get('/api/signature').json()['version']
    original=m.render_pdf
    def fail(*args,**kwargs):raise RuntimeError('forced PDF failure')
    monkeypatch.setattr(m,'render_pdf',fail)
    result=approve(client,rid).json();assert result['file_status']=='failed'
    with Session(m.engine) as db:
        snapshot=db.get(m.ApprovalSignature,rid)
        saved=snapshot.content
        assert snapshot.signature_version==before and snapshot.watermark.endswith('-3天')
    client.post('/api/signature',json=signature_payload())
    assert client.get('/api/signature').json()['version']!=before
    monkeypatch.setattr(m,'render_pdf',original)
    result=client.post(f'/api/requests/{rid}/retry').json();assert result['file_status']=='ready'
    pdf=PdfReader(io.BytesIO(client.get('/api/documents/'+result['documents'][0]['id']).content))
    embedded=[image.image.convert('RGB') for page in pdf.pages for image in page.images]
    assert len(embedded)==1
    assert embedded[0].tobytes()==Image.open(io.BytesIO(saved)).convert('RGB').tobytes()
    assert '审批前预览' not in ''.join(p.extract_text() for p in pdf.pages)


def test_watermark_is_pure_black_and_survives_binary_threshold():
    source=Image.new('RGB',(600,180),'white');raw=io.BytesIO();source.save(raw,format='PNG')
    marked=Image.open(io.BytesIO(m.watermarked_signature(raw.getvalue(),'测试同学（请假人）-2026-10-10-3天')))
    colors=set(marked.getdata())
    assert colors=={(0,0,0),(255,255,255)}
    for threshold in [1,64,128,200,254]:
        binary=marked.convert('L').point(lambda value:255 if value>=threshold else 0)
        assert binary.convert('RGB').tobytes()==marked.tobytes()
    black=sum(pixel==(0,0,0) for pixel in marked.getdata())
    assert black>10000


@pytest.mark.parametrize('raw',[b'not an image',b'<svg/>',b'GIF89a'])
def test_invalid_signature_rejected(client,raw):
    login(client,'counselor-a',with_signature=False)
    assert client.post('/api/signature',json={'image':base64.b64encode(raw).decode()}).status_code==422
    assert client.get('/api/signature').json()['configured'] is False


def test_signature_metadata_stripped_and_access_is_private(client):
    from PIL.PngImagePlugin import PngInfo
    image=Image.new('RGB',(600,180),'white'); metadata=PngInfo();metadata.add_text('private','secret')
    raw=io.BytesIO();image.save(raw,format='PNG',pnginfo=metadata)
    login(client,'counselor-a',with_signature=False)
    assert client.post('/api/signature',json={'image':base64.b64encode(raw.getvalue()).decode()}).status_code==200
    response=client.get('/api/signature/image');assert response.headers['cache-control']=='no-store'
    assert not Image.open(io.BytesIO(response.content)).info
    login(client,'counselor-b',with_signature=False)
    assert client.get('/api/signature/image').status_code==404


def test_operator_removal_revokes_existing_session_and_preserves_history(client):
    login(client);rid=submit(client)['id']
    data=roster_payload();data['students']=[p for p in data['students'] if p['user_id']!='student-a']
    with Session(m.engine) as db:m.sync_directory(db,DirectoryConfig.model_validate(data))
    assert client.get('/api/me').status_code==403
    assert client.post('/api/demo/login',json={'person_id':'student-a'}).status_code==400
    with Session(m.engine) as db:
        assert db.get(m.Person,'student-a') and db.get(m.Request,rid).snapshot['name']=='演示学生甲'


def test_invalid_operator_file_fails_startup_before_db_changes(client,tmp_path,monkeypatch):
    source=tmp_path/'invalid.json';source.write_text('{"version":1}')
    monkeypatch.setenv('RELATIONSHIPS_PATH',str(source))
    with pytest.raises(RuntimeError,match='operator relationship'):
        with TestClient(m.app):pass
    login(client);assert client.get('/api/me').json()['profile']['class_id']=='class-a'


def test_cross_origin_mutations_rejected(client):
    response=client.post('/api/demo/login',json={'person_id':'student-a'},headers={'Origin':'https://untrusted.example'})
    assert response.status_code==403 and response.headers['cache-control']=='no-store'


def test_concurrent_class_counselors_do_not_double_sign(client):
    login(client);rid=submit(client)['id']
    sessions=[]
    for person in ['counselor-a','counselor-c']:
        reviewer=TestClient(m.app)
        login(reviewer,person)
        preview=reviewer.post(f'/api/requests/{rid}/preview',json={'opinion':person}).json()
        sessions.append((dict(reviewer.cookies),preview['id'],person))
        reviewer.close()
    # Use clients without lifespan startup while two requests race on the same database.
    def sign(args):
        cookie,pid,opinion=args
        reviewer=TestClient(m.app);reviewer.cookies.update(cookie)
        try:return reviewer.post(f'/api/requests/{rid}/decision',json={'outcome':'approved','opinion':opinion,'preview_id':pid}).status_code
        finally:reviewer.close()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(sign,sessions))
    assert sorted(results)==[200,409]
    with Session(m.engine) as db:
        assert db.scalar(select(func.count()).select_from(m.Decision))==1
        assert db.scalar(select(func.count()).select_from(m.ApprovalSignature))==1
        assert db.scalar(select(func.count()).select_from(m.Document))==1
