import io

import pytest
from pypdf import PdfReader

from test_workflow import client, login, payload, submit, approve


@pytest.mark.parametrize('layout,single_item,count,table',[
    ('combined',True,1,False),
    ('combined',False,1,True),
    ('separate',False,2,False),
])
def test_formal_document_prose_and_item_scope(client,layout,single_item,count,table):
    login(client)
    body=payload(layout)
    if single_item:body['items']=body['items'][:1]
    rid=submit(client,body)['id']
    login(client,'counselor-a')
    result=approve(client,rid).json()
    assert result['file_status']=='ready' and len(result['documents'])==count
    texts=[]
    for doc in result['documents']:
        pdf=PdfReader(io.BytesIO(client.get('/api/documents/'+doc['id']).content))
        text=''.join(page.extract_text() for page in pdf.pages).replace('\n','')
        texts.append(text)
        assert '\x00' not in text
        assert '兹证明' in text and '复旦大学管理学院工商管理专业2026级学生' in text
        assert '学号：student-a' in text and '辅导员签字：' in text
        assert '姓名：' not in text and '请假期间：' not in text and '审批时间：' not in text
        assert ('请假以下事项：' in text)==table
        assert ('特此证明。' in text)==(not table)
        assert len(pdf.pages)==1
    if layout=='separate':
        assert '组织行为学' in texts[0] and '志愿者活动' not in texts[0]
        assert '志愿者活动' in texts[1] and '组织行为学' not in texts[1]
    elif not single_item:
        assert '组织行为学' in texts[0] and '志愿者活动' in texts[0]
