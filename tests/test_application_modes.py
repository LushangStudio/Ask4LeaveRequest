import io
import pytest
from pypdf import PdfReader
from test_workflow import client, login, payload, submit, approve


def mode_payload(mode, layout='combined'):
    body=payload(layout);body['mode']=mode
    if mode=='date_range':body['items']=[]
    else:
        body.pop('starts');body.pop('ends')
    return body


def pdf_text(response):
    return ''.join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages).replace('\n','')


@pytest.mark.parametrize('mode,layout,count',[('date_range','combined',1),('items','combined',1),('items','separate',2)])
def test_modes_preview_approval_and_pdf(client,mode,layout,count):
    login(client)
    body=mode_payload(mode,layout)
    body['reason']='  参加学术交流。  '
    row=submit(client,body)
    assert row['mode']==mode
    assert row['ends']==('2026-10-03' if mode=='date_range' else '2026-10-02')
    login(client,'counselor-a')
    preview=client.post('/api/requests/'+row['id']+'/preview',json={}).json()
    text=pdf_text(client.get(f"/api/previews/{preview['id']}/0"))
    assert '拟同意' in text and '该生因参加学术交流，经辅导员审核' in text
    result=approve(client,row['id']).json()
    assert len(result['documents'])==count
    for index,doc in enumerate(result['documents']):
        text=pdf_text(client.get('/api/documents/'+doc['id']))
        assert '拟同意' not in text and '该生因参加学术交流，经辅导员审核' in text
        if mode=='date_range':
            assert '共 3 天' in text and '组织行为学' not in text
        else:
            assert '共 2 天' not in text and '共 3 天' not in text
            if layout=='separate':
                assert body['items'][index]['title'] in text
                assert body['items'][1-index]['title'] not in text


def test_items_use_latest_date_not_input_order(client):
    login(client)
    body=mode_payload('items');body['items'].reverse()
    row=submit(client,body)
    assert row['starts']=='2026-10-01' and row['ends']=='2026-10-02'
    assert row['attachments_retained_through']=='2026-11-02'


@pytest.mark.parametrize('change',[
    {'mode':'date_range','items':payload()['items']},
    {'mode':'date_range','items':[],'starts':None},
    {'mode':'date_range','items':[],'layout':'separate'},
    {'mode':'items'},
    {'mode':'invalid'},
])
def test_modes_reject_ambiguous_payload(client,change):
    login(client)
    body=payload();body.update(change)
    assert client.post('/api/requests',json=body).status_code==422


def test_items_require_at_least_one_and_legacy_still_works(client):
    login(client)
    body=mode_payload('items');body['items']=[]
    assert client.post('/api/requests',json=body).status_code==422
    assert submit(client,payload())['mode']=='legacy'


def test_existing_sqlite_database_adds_mode_without_losing_requests(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text, inspect
    from app import main as m
    engine=create_engine('sqlite:///'+str(tmp_path/'legacy.db'),connect_args={'check_same_thread':False})
    monkeypatch.setattr(m,'engine',engine)
    monkeypatch.setenv('APP_MODE','demo')
    try:
        with TestClient(m.app) as c:
            login(c);row=submit(c,payload())
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE leave_requests DROP COLUMN mode'))
        with TestClient(m.app) as c:
            login(c)
            migrated=c.get('/api/requests/'+row['id']).json()
            assert migrated['mode']=='legacy'
            assert migrated['reason']==row['reason'] and migrated['items']==row['items']
            assert 'mode' in {column['name'] for column in inspect(engine).get_columns('leave_requests')}
    finally:
        engine.dispose()
