"""Bounded request bodies and process-local abuse protection.

Use one Uvicorn worker (the deployed configuration). Client addresses come from
ASGI, never directly from untrusted forwarding headers. The proxy must overwrite
X-Forwarded-For and Uvicorn must trust only the loopback proxy.
"""
import hashlib
import json
import math
import threading
import time
from collections import OrderedDict


class HTTPResourceLimits:
    def __init__(self, app, max_body=4_300_000, window=60, ip_limit=600,
                 expensive_limit=120, max_clients=10000, clock=time.monotonic):
        self.app = app
        self.max_body = max_body
        self.window = window
        self.ip_limit = ip_limit
        self.expensive_limit = expensive_limit
        self.max_clients = max_clients
        self.clock = clock
        self.buckets = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key, limit):
        now = self.clock()
        with self.lock:
            # Expired entries are ordered by their fixed-window start time.
            while self.buckets and next(iter(self.buckets.values()))[0] + self.window <= now:
                self.buckets.popitem(last=False)
            entry = self.buckets.get(key)
            if entry is None:
                # Fail closed under a flood of new identities; do not evict active
                # counters and let attackers reset their budget.
                if len(self.buckets) >= self.max_clients:
                    return self.window
                entry = [now, 0]
                self.buckets[key] = entry
            if entry[1] >= limit:
                return max(1, math.ceil(entry[0] + self.window - now))
            entry[1] += 1
            return 0

    async def reject(self, send, status, detail, retry=None):
        headers = [(b'content-type', b'application/json'), (b'cache-control', b'no-store'),
                   (b'x-content-type-options', b'nosniff'), (b'referrer-policy', b'no-referrer')]
        if retry is not None:
            headers.append((b'retry-after', str(retry).encode()))
        await send({'type': 'http.response.start', 'status': status, 'headers': headers})
        await send({'type': 'http.response.body', 'body': json.dumps({'detail': detail}).encode()})

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            with self.lock:
                self.buckets.clear()
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        has_query = bool(scope.get('query_string') or scope.get('state', {}).get('test_login_query'))
        if path.startswith('/api/') or has_query:
            ip = (scope.get('client') or ('unknown', 0))[0]
            key = hashlib.sha256(ip.encode()).digest()
            retry = self.allow(('all', key), self.ip_limit)
            expensive = scope['method'] not in {'GET', 'HEAD'} or '/previews/' in path or '/auth/' in path or has_query
            if not retry and expensive:
                retry = self.allow(('expensive', key), self.expensive_limit)
            if retry:
                return await self.reject(send, 429, '请求过于频繁，请稍后重试', retry)
        headers = dict(scope['headers'])
        length = headers.get(b'content-length')
        if length is not None:
            if not length.isdigit():
                return await self.reject(send, 400, '请求长度无效')
            if int(length) > self.max_body:
                return await self.reject(send, 413, '请求内容过大')
        # Check the actual stream, including chunked/incorrectly declared bodies,
        # before any mutation can be dispatched to the application.
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > self.max_body:
                return await self.reject(send, 413, '请求内容过大')
            if not message.get('more_body', False):
                break
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, bounded_receive, send)
