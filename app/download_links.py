"""Short-lived PDF capabilities. Shared persistent key, no login cookie required."""
import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
from pathlib import Path

TTL = 180


def key(directory):
    path = Path(directory) / 'download-link.key'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.download-key-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    return path.read_bytes()


def issue(directory, claims):
    claims = {**claims, 'exp': int(time.time()) + TTL}
    body = base64.urlsafe_b64encode(json.dumps(claims, separators=(',', ':')).encode()).decode().rstrip('=')
    signature = hmac.new(key(directory), body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + signature


def verify(directory, token):
    try:
        body, signature = token.split('.')
        expected = hmac.new(key(directory), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError('signature')
        claims = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        if claims['exp'] <= time.time():
            raise ValueError('expired')
        return claims
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('下载链接已失效，请返回应用重新获取') from exc
