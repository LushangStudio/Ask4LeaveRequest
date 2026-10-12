import re
from test_workflow import client,login,submit,payload,approve

def test_generated_names_are_random_distinct_and_stable(client):
    names=[]
    for _ in range(2):
        login(client);rid=submit(client,payload('separate'))['id'];login(client,'counselor-a')
        result=approve(client,rid).json()
        for doc in result['documents']:
            assert re.fullmatch(r'[0-9a-f]{32}\.pdf',doc['name'])
            names.append(doc['name'])
            assert f'filename="{doc["name"]}"' in client.get('/api/documents/'+doc['id']).headers['content-disposition']
        assert client.post(f'/api/requests/{rid}/retry').json()['documents']==result['documents']
    assert len(set(names))==4

def test_preview_download_names_are_random_and_match_http_response(client):
    login(client);rid=submit(client,payload('separate'))['id'];login(client,'counselor-a')
    first=client.post(f'/api/requests/{rid}/preview',json={}).json()
    for i,name in enumerate(first['filenames']):
        assert re.fullmatch(r'[0-9a-f]{32}\.pdf',name)
        assert f'filename="{name}"' in client.get(f"/api/previews/{first['id']}/{i}").headers['content-disposition']
    second=client.post(f'/api/requests/{rid}/preview',json={}).json()
    assert not set(first['filenames']) & set(second['filenames'])
