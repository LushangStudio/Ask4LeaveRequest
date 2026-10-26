from test_workflow import client, login, submit, approve
from app import main as m
from app import download_links as links


def test_anonymous_repeat_expiry_tamper_and_withdrawal(client, tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'DATA_DIR', tmp_path)
    login(client)
    row = submit(client)
    login(client, 'counselor-a')
    approved = approve(client, row['id']).json()
    resource = {'kind': 'documents', 'id': approved['documents'][0]['id']}
    login(client, 'student-b')
    assert client.post('/api/download-links', json=resource).status_code == 404
    login(client)
    result = client.post('/api/download-links', json=resource)
    assert result.status_code == 200
    assert result.json()['expires_in'] == 180
    url = '/api/' + result.json()['path']
    client.cookies.clear()
    assert client.post('/api/download-links', json=resource).status_code == 401
    for _ in range(3):
        response = client.get(url)
        assert response.status_code == 200
        assert response.content.startswith(b'%PDF')
        assert response.headers['content-disposition'].startswith('attachment;')
        assert response.headers['cache-control'] == 'no-store'
    assert client.get(url + 'x').status_code == 410
    with monkeypatch.context() as patch:
        patch.setattr(links.time, 'time', lambda: 9999999999)
        assert client.get(url).status_code == 410
    login(client, 'counselor-a')
    assert client.post(f"/api/requests/{row['id']}/withdraw", json={}).status_code == 200
    client.cookies.clear()
    assert client.get(url).status_code in (404, 409, 410)


def test_preview_link_invalidated_after_approval(client, tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'DATA_DIR', tmp_path)
    login(client)
    row = submit(client)
    login(client, 'counselor-a')
    preview = client.post(f"/api/requests/{row['id']}/preview", json={'opinion': '同意'}).json()
    result = client.post('/api/download-links', json={'kind':'previews', 'id':preview['id'], 'position':0})
    assert result.status_code == 200
    url = '/api/' + result.json()['path']
    client.cookies.clear()
    assert client.get(url).status_code == 200
    login(client, 'counselor-a')
    assert approve(client, row['id']).status_code == 200
    client.cookies.clear()
    assert client.get(url).status_code in (404, 409, 410)


def test_key_persists_and_is_private(tmp_path):
    token = links.issue(tmp_path, {'id':'example'})
    assert links.verify(tmp_path, token)['id'] == 'example'
    assert (tmp_path / 'download-link.key').stat().st_mode & 0o777 == 0o600
