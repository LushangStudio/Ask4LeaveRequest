import io
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from PIL import Image, ImageDraw
from app import main as m

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_MODE','demo')
    mysql_url=os.getenv('MYSQL_TEST_URL')
    if mysql_url:
        schema='ask4leave_ci_'+uuid.uuid4().hex
        admin=create_engine(mysql_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4'))
        test_engine=create_engine(make_url(mysql_url).set(database=schema),pool_pre_ping=True)
    else:
        test_engine=create_engine('sqlite:///'+str(tmp_path/'test.db'),connect_args={'check_same_thread':False})
    monkeypatch.setattr(m,'engine',test_engine)
    try:
        with TestClient(m.app) as c: yield c
    finally:
        test_engine.dispose()
        if mysql_url:
            assert schema.startswith('ask4leave_ci_')
            with admin.begin() as connection:
                connection.execute(text(f'DROP DATABASE `{schema}`'))
            admin.dispose()

def signature_payload():
    image=Image.new('RGB',(600,180),'white'); draw=ImageDraw.Draw(image)
    draw.line([(60,130),(150,35),(200,130),(310,45),(270,140),(450,60),(520,100)],fill='black',width=8)
    output=io.BytesIO();image.save(output,format='PNG')
    import base64
    return {'image':base64.b64encode(output.getvalue()).decode()}

def login(c,person='student-a',with_signature=True):
    assert c.post('/api/demo/login',json={'person_id':person}).status_code==200
    if with_signature and c.get('/api/me').json()['role']=='counselor' and not c.get('/api/signature').json()['configured']:
        assert c.post('/api/signature',json=signature_payload()).status_code==200

def payload(layout='combined'):
    return {'reason':'参加校外学术交流，申请请假。','starts':'2026-10-01','ends':'2026-10-03','layout':layout,'idempotency_key':str(uuid.uuid4()),'items':[{'kind':'course','title':'组织行为学','day':'2026-10-01','time':'第 1–2 节'},{'kind':'activity','title':'志愿者活动','day':'2026-10-02','time':'14:00–16:00'}]}
def submit(c,body=None):
    r=c.post('/api/requests',json=body or payload());assert r.status_code==201,r.text;return r.json()
def approve(c,rid):
    preview=c.post(f'/api/requests/{rid}/preview',json={'opinion':'同意'})
    body={'outcome':'approved','opinion':'同意'}
    if preview.status_code==200:body['preview_id']=preview.json()['id']
    return c.post(f'/api/requests/{rid}/decision',json=body)

@pytest.mark.parametrize('layout,count',[('combined',1),('separate',2)])
def test_full_flow_pdf_and_persistence(client,layout,count):
    c=client;login(c);body=payload(layout);row=submit(c,body)
    assert submit(c,body)['id']==row['id']
    login(c,'counselor-a');r=approve(c,row['id']);assert r.status_code==200,r.text
    result=r.json();assert result['status']=='approved';assert result['file_status']=='ready',result
    assert len(result['documents'])==count
    assert approve(c,row['id']).json()['documents']==result['documents']
    assert c.post(f"/api/requests/{row['id']}/retry").status_code==200
    login(c)
    texts=[]
    for d in result['documents']:
        response=c.get('/api/documents/'+d['id']);assert response.status_code==200
        pdf=PdfReader(io.BytesIO(response.content));texts.append('\n'.join(p.extract_text() for p in pdf.pages))
        assert 'student-a' in texts[-1] and 'counselor-a' in texts[-1]
        assert '非正式凭证' in texts[-1]
    assert '组织行为学' in ''.join(texts) and '志愿者活动' in ''.join(texts)
    if count==2: assert '志愿者活动' not in texts[0] and '组织行为学' not in texts[1]
    with Session(m.engine) as db:
        assert db.scalar(select(func.count()).select_from(m.Request))==1
        assert db.scalar(select(func.count()).select_from(m.Item))==2
        assert db.scalar(select(func.count()).select_from(m.Decision))==1
        assert db.scalar(select(func.count()).select_from(m.Document))==count

def test_permissions(client):
    c=client;assert c.get('/api/requests').status_code==401
    login(c);row=submit(c);rid=row['id'];assert approve(c,rid).status_code==403
    for person in ['student-b','counselor-b']:
        login(c,person);assert c.get('/api/requests').json()==[]
        assert c.get('/api/requests/'+rid).status_code==404
        assert approve(c,rid).status_code==404
    login(c,'counselor-a');row=approve(c,rid).json()
    login(c,'student-b');assert c.get('/api/documents/'+row['documents'][0]['id']).status_code==404
    login(c,'counselor-a');assert c.post('/api/requests',json=payload()).status_code==403

def test_rejection_validation_and_idempotency_conflict(client):
    c=client;login(c);body=payload();rid=submit(c,body)['id']
    body['reason']='不同内容';assert c.post('/api/requests',json=body).status_code==409
    bad=payload();bad['ends']='2026-09-01';assert c.post('/api/requests',json=bad).status_code==422
    bad=payload();bad['items'][0]['day']='2026-12-01';assert c.post('/api/requests',json=bad).status_code==422
    bad=payload();bad['reason']='  ';assert c.post('/api/requests',json=bad).status_code==422
    login(c,'counselor-a')
    assert c.post(f'/api/requests/{rid}/decision',json={'outcome':'rejected'}).status_code==422
    r=c.post(f'/api/requests/{rid}/decision',json={'outcome':'rejected','opinion':'信息不完整'}).json()
    assert r['documents']==[] and r['status']=='rejected'
    assert c.post(f'/api/requests/{rid}/retry').status_code==409
    assert approve(c,rid).status_code==409

def test_generation_failure_retry_atomic(client,monkeypatch):
    c=client;login(c);rid=submit(c,payload('separate'))['id'];login(c,'counselor-a')
    original=m.render_pdf;calls=0
    def fail_second(*args):
        nonlocal calls
        calls+=1
        if calls==2:raise RuntimeError('simulated failure')
        return original(*args)
    monkeypatch.setattr(m,'render_pdf',fail_second)
    result=approve(c,rid).json();assert result['status']=='approved' and result['file_status']=='failed'
    assert result['documents']==[]
    monkeypatch.setattr(m,'render_pdf',original)
    r=c.post(f'/api/requests/{rid}/retry').json();assert r['file_status']=='ready' and len(r['documents'])==2
    assert c.post(f'/api/requests/{rid}/retry').json()['documents']==r['documents']

def test_immutable_snapshot_and_long_text(client):
    c=client;login(c);body=payload();body['reason']='较长的中文请假说明。'*300;rid=submit(c,body)['id']
    with Session(m.engine) as db:
        db.get(m.Person,'student-a').name='修改后的姓名';db.commit()
    login(c,'counselor-a');result=approve(c,rid).json();assert result['file_status']=='ready'
    pdf=PdfReader(io.BytesIO(c.get('/api/documents/'+result['documents'][0]['id']).content))
    text=''.join(p.extract_text() for p in pdf.pages)
    assert '修改后的姓名' not in text and 'student-a' in text
    assert len(pdf.pages)>1 and '志愿者活动' in text

def test_logout_and_production_guard(client,monkeypatch):
    login(client);client.post('/api/logout');assert client.get('/api/me').status_code==401
    monkeypatch.setenv('APP_MODE','production')
    with pytest.raises(RuntimeError,match='ehall'):
        with TestClient(m.app): pass
