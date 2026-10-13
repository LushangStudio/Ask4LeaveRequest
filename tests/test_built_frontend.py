"""Exercise the built HTML/assets through FastAPI at both supported prefixes."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

from app import main as m
from test_workflow import client


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.assets.append(attrs['src'])
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.assets.append(attrs['href'])


@pytest.mark.parametrize('prefix', ['', '/leave'])
def test_built_frontend_assets_resolve_at_supported_prefix(client, prefix):
    # CI builds before pytest; a missing dist is a failure, not a skipped check.
    assert (m.FRONTEND_DIST / 'index.html').is_file(), 'Run npm ci && npm run build first'
    outer = Starlette(routes=[Mount(prefix or '/', app=m.app)])
    with TestClient(outer) as browser:
        response = browser.get(prefix + '/')
        assert response.status_code == 200
        parser = AssetParser()
        parser.feed(response.text)
        assert len(parser.assets) >= 2
        for relative in parser.assets:
            assert not relative.startswith(('/', 'http:', 'https:'))
            path = urlsplit(urljoin('http://testserver' + prefix + '/', relative)).path
            assert path.startswith(prefix + '/assets/')
            asset = browser.get(path)
            assert asset.status_code == 200
            assert len(asset.content) > 0
            assert 'text/html' not in asset.headers['content-type']
