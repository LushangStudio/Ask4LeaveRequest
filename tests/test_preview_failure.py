"""PDF delivery/generation failures must not prevent recording an approval."""
from test_workflow import client, login, submit
from app import main as m


def test_approval_survives_unavailable_pdf_and_can_retry(client, monkeypatch):
    login(client)
    row = submit(client)
    login(client, 'counselor-a')
    preview = client.post(f"/api/requests/{row['id']}/preview", json={'opinion':'已核对申请信息'}).json()
    original = m.render_pdf
    def unavailable(*args, **kwargs):
        raise RuntimeError('simulated PDF failure')
    monkeypatch.setattr(m, 'render_pdf', unavailable)
    # No successful PDF fetch is needed: the signed server snapshot is enough.
    result = client.post(f"/api/requests/{row['id']}/decision", json={
        'outcome':'approved', 'opinion':'已核对申请信息', 'preview_id':preview['id']})
    assert result.status_code == 200
    assert result.json()['status'] == 'approved'
    assert result.json()['file_status'] == 'failed'
    monkeypatch.setattr(m, 'render_pdf', original)
    retried = client.post(f"/api/requests/{row['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()['status'] == 'approved'
    assert retried.json()['file_status'] == 'ready'
