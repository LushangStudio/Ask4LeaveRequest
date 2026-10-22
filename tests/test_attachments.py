import base64
import copy
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app import main as m
from app.attachments import MAX_ATTACHMENT_BYTES
from test_workflow import client, login, payload, submit


def attachment(name='中文证明.pdf', content=b'%PDF-1.7\nproof'):
    return {'name':name,'data':base64.b64encode(content).decode()}


def test_attachments_atomic_idempotent_and_private(client):
    login(client)
    body=payload();body['attachments']=[attachment(),attachment('说明.txt',b'details'),attachment('photo.png',b'opaque bytes')]
    row=submit(client,body)
    assert len(row['attachments'])==3
    assert 'data' not in row['attachments'][0]
    assert submit(client,body)['attachments']==row['attachments']
    path='/api/attachments/'+row['attachments'][0]['id']
    response=client.get(path)
    assert response.content==b'%PDF-1.7\nproof'
    assert response.headers['content-disposition'].startswith('attachment;')
    assert "filename*=UTF-8''%E4%B8%AD" in response.headers['content-disposition']
    assert response.headers['content-type']=='application/octet-stream'
    assert response.headers['x-content-type-options']=='nosniff'
    assert response.headers['cache-control']=='no-store'
    changed=copy.deepcopy(body);changed['attachments'][0]=attachment(content=b'changed')
    assert client.post('/api/requests',json=changed).status_code==409
    for identity in ['student-b','counselor-b']:
        login(client,identity)
        assert client.get(path).status_code==404
    login(client,'counselor-a')
    assert client.get(path).status_code==200
    assert client.get('/api/requests/'+row['id']).json()['attachments']==row['attachments']
    client.cookies.clear()
    assert client.get(path).status_code==401
    with Session(m.engine) as db:
        assert db.scalar(select(func.count()).select_from(m.Attachment))==3
        assert db.scalar(select(func.count()).select_from(m.Request))==1


def test_invalid_attachments_do_not_create_request(client):
    login(client)
    invalid=[ [attachment()]*4, [attachment(content=b'')], [{'name':'x','data':'not base64!'}],
              [attachment('bad\r\nname')], [attachment(content=b'x'*(MAX_ATTACHMENT_BYTES+1))] ]
    for files in invalid:
        body=payload();body['attachments']=files
        assert client.post('/api/requests',json=body).status_code==422
    with Session(m.engine) as db:
        assert db.scalar(select(func.count()).select_from(m.Request))==0
        assert db.scalar(select(func.count()).select_from(m.Attachment))==0


def test_three_max_size_files_and_filename_sanitization(client):
    login(client)
    body=payload();body['attachments']=[attachment('../文件.txt',b'x'*MAX_ATTACHMENT_BYTES)]*3
    row=submit(client,body)
    assert all(a['size']==MAX_ATTACHMENT_BYTES and a['name']=='文件.txt' for a in row['attachments'])
    assert len(client.get('/api/attachments/'+row['attachments'][0]['id']).content)==MAX_ATTACHMENT_BYTES


def test_no_attachment_backward_compatibility(client):
    login(client)
    body=payload();row=submit(client,body)
    assert row['attachments']==[]
    body['attachments']=[]
    assert submit(client,body)['id']==row['id']
