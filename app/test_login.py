"""Explicitly enabled, namespace-limited test authentication."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

__test__ = False


class TestLoginConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = False
    secret: SecretStr | None = None

    @model_validator(mode='after')
    def require_private_key(self):
        if self.enabled and (self.secret is None or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', self.secret.get_secret_value())):
            raise ValueError('Enabled test login requires a private 32-128 character URL-safe secret')
        return self

    def secret_digest(self):
        return hashlib.sha256((self.secret.get_secret_value() if self.secret else '').encode()).hexdigest()


def load_test_login(path):
    if not path: return TestLoginConfig()
    try:
        source = Path(path)
        if source.stat().st_size > 65536: raise ValueError()
        return TestLoginConfig.model_validate(json.loads(source.read_text(encoding='utf-8')))
    except Exception:
        raise RuntimeError('Invalid private test-login config; check path, enabled flag and secret format') from None


class TestQueryRedaction:
    """Remove credentials from the ASGI scope before Uvicorn can log the response."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            pairs = parse_qsl(scope.get('query_string', b'').decode('utf-8', errors='replace'), keep_blank_values=True)
            if any(key in {'secret', 'uid'} for key, _ in pairs):
                # Preserve only a one-way digest, never the URL credential, in request state.
                secrets = [value for key, value in pairs if key == 'secret']
                users = [value for key, value in pairs if key == 'uid']
                scope.setdefault('state', {})['test_login_query'] = {
                    'valid_shape': len(secrets) == 1 and len(users) == 1,
                    'secret_digest': hashlib.sha256(secrets[0].encode()).hexdigest() if len(secrets) == 1 else '',
                    'uid': users[0] if len(users) == 1 else '',
                }
                scope['query_string'] = urlencode([(key, value) for key, value in pairs if key not in {'secret', 'uid'}]).encode()
            if scope.get('path','').rstrip('/') in {'/api/auth/callback','/api/auth/sso-logout'}:
                downstream=dict(scope)
                scope['query_string']=b''
                await self.app(downstream,receive,send)
                return
        await self.app(scope, receive, send)
