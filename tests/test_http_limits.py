import asyncio
import pytest
from app.http_limits import HTTPResourceLimits


def probe(app, *, chunks=(b'',), headers=(), path='/api/requests', ip='127.0.0.1'):
    sent = []
    async def run():
        messages = iter([{'type':'http.request','body': chunk,'more_body': i < len(chunks)-1} for i,chunk in enumerate(chunks)])
        async def receive(): return next(messages)
        async def send(message): sent.append(message)
        await app({'type':'http','path':path,'method':'POST','headers':list(headers),
                   'client':(ip,123),'query_string':b''},receive,send)
    asyncio.run(run())
    return sent


async def endpoint(scope, receive, send):
    await receive()
    await send({'type':'http.response.start','status':204,'headers':[]})
    await send({'type':'http.response.body','body':b''})


@pytest.mark.parametrize('headers', [(), ((b'content-length',b'1'),)])
def test_actual_stream_limit_before_mutation(headers):
    called=[]
    async def mutation(*args):called.append(True)
    app=HTTPResourceLimits(mutation,max_body=10)
    assert probe(app,chunks=(b'123456',b'78901'),headers=headers)[0]['status']==413
    assert not called


def test_exact_body_boundary_and_declared_limit():
    app=HTTPResourceLimits(endpoint,max_body=10)
    assert probe(app,chunks=(b'12345',b'67890'))[0]['status']==204
    assert probe(app,headers=((b'content-length',b'11'),))[0]['status']==413
    assert probe(app,headers=((b'content-length',b'invalid'),))[0]['status']==400


def test_ip_budget_cannot_be_reset_by_cookie_or_forwarding_header():
    now=[0]
    app=HTTPResourceLimits(endpoint,expensive_limit=2,clock=lambda:now[0])
    assert probe(app)[0]['status']==204
    assert probe(app,headers=((b'cookie',b'leave_session=fake'),))[0]['status']==204
    result=probe(app,headers=((b'x-forwarded-for',b'other'),))[0]
    assert result['status']==429 and (b'retry-after',b'60') in result['headers']
    assert probe(app,ip='127.0.0.2')[0]['status']==204
    now[0]=60
    assert probe(app)[0]['status']==204


def test_counter_storage_bounded_without_evicting_active_budget():
    app=HTTPResourceLimits(endpoint,max_clients=2)
    assert probe(app)[0]['status']==204
    assert probe(app,ip='new')[0]['status']==429
    assert len(app.buckets)==2
