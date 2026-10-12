from datetime import date,timedelta
import pytest
from app import main as m
from app.leave_dates import leave_end_limit
from test_workflow import client,login,payload

@pytest.mark.parametrize('today,limit',[
    ('2026-10-12','2027-01-12'),('2026-01-31','2026-04-30'),
    ('2026-11-30','2027-02-28'),('2023-11-30','2024-02-29'),
    ('2026-12-31','2027-03-31')])
def test_three_calendar_months_clamp_shorter_months(today,limit):
    assert leave_end_limit(date.fromisoformat(today)).isoformat()==limit

def test_latest_allowed_end_date_is_inclusive(client,monkeypatch):
    cap=date(2027,1,12);monkeypatch.setattr(m,'leave_end_limit',lambda:cap)
    login(client);body=payload();body['ends']=cap.isoformat()
    assert client.post('/api/requests',json=body).status_code==201
    assert client.get('/api/runtime').json()['max_end_date']==cap.isoformat()

def test_api_rejects_end_after_limit_even_without_browser_validation(client,monkeypatch):
    cap=date(2027,1,12);monkeypatch.setattr(m,'leave_end_limit',lambda:cap)
    login(client);body=payload();body['ends']=(cap+timedelta(days=1)).isoformat()
    response=client.post('/api/requests',json=body)
    assert response.status_code==422
    assert '最晚 2027-01-12' in response.json()['detail'][0]['msg']
