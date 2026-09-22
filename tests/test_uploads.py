import hashlib
import io
import urllib.error

import pytest
from fastapi.testclient import TestClient

from cad.app import create_app
from cad import uploads, preview
from cad.auth import PasswordGate, COOKIE


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client


def put(client, project='dripper', name='reference.step', note='Fit this edge', data=b'example'):
    return client.post(f'/projects/{project}/api/uploads',
                       files={'file': (name, data, 'application/octet-stream')},
                       data={'note': note})


def test_lifecycle_isolation_and_no_design_changes(client):
    before = client.get('/projects/dripper/api/state').json()
    other = client.post('/api/projects', json={'name': 'Other'}).json()['id']
    r = put(client, name='参考 <part>.html', note='<script>not executed</script>')
    assert r.status_code == 201, r.text
    item = r.json()
    assert item['sha256'] == hashlib.sha256(b'example').hexdigest()
    path = f'/projects/dripper/downloads/uploads/{item["id"]}/file'
    r = client.get(path)
    assert r.content == b'example'
    assert r.headers['content-type'] == 'application/octet-stream'
    assert r.headers['content-disposition'].startswith('attachment;')
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert client.head(path).content == b''
    assert client.get(path, headers={'Range': 'bytes=0-2'}).content == b'exa'
    assert client.get(path.replace('dripper', other)).status_code == 404
    assert client.get(f'/projects/{other}/api/uploads').json()['uploads'] == []
    api = f'/projects/dripper/api/uploads/{item["id"]}'
    assert client.patch(api, json={'note': 'Changed', 'version': 1}).status_code == 200
    assert client.patch(api, json={'note': 'Stale', 'version': 1}).status_code == 409
    assert client.patch(api.replace('dripper', other), json={'note': 'x', 'version': 2}).status_code == 404
    assert client.get('/projects/dripper/api/uploads').json()['uploads'][0]['note'] == 'Changed'
    assert client.get('/projects/dripper/api/state').json() == before
    assert client.delete(api).status_code == 204
    assert client.get(path).status_code == 404
    assert client.get('/projects/dripper/api/uploads').json()['uploads'] == []
    assert client.get('/api/uploads').status_code == 404


@pytest.mark.parametrize('name', ['../bad', 'folder/bad', 'folder\\bad', '..'])
def test_bad_names(client, name):
    assert put(client, name=name).status_code == 422


def test_limits_and_origin(client, monkeypatch):
    assert put(client, note='x'*4001).status_code == 422
    assert put(client, data=b'x'*(uploads.MAX_FILE+1)).status_code == 413
    assert client.post('/projects/dripper/api/uploads', content=b'x'*(uploads.MAX_BODY+1)).status_code == 413
    assert client.post('/projects/dripper/api/uploads', headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/projects/dripper/api/uploads', files=[('file', ('a', b'a')), ('file', ('b', b'b'))]).status_code == 400
    monkeypatch.setattr(uploads, 'MAX_FILES', 1)
    assert put(client).status_code == 201
    assert put(client).status_code == 413
    assert len(client.get('/projects/dripper/api/uploads').json()['uploads']) == 1


def test_persistence(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        row = put(c).json()
    with TestClient(create_app(tmp_path)) as c:
        assert c.get('/projects/dripper/api/uploads').json()['uploads'] == [row]


def test_authenticated_gateway(client, monkeypatch):
    def urlopen(req, timeout):
        response = client.request(req.get_method(), req.full_url.removeprefix(preview.ORIGIN),
                                  content=req.data, headers=dict(req.header_items()))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(req.full_url, response.status_code, 'error',
                                         response.headers, io.BytesIO(response.content))

        class Wrapped:
            code = response.status_code
            headers = response.headers

            def read(self):
                return response.content

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return Wrapped()

    monkeypatch.setattr(preview.urllib.request, 'urlopen', urlopen)
    gate = PasswordGate({'salt': '00'*16, 'hash': '00'*64})
    monkeypatch.setattr(preview.app.state, 'gate', gate)
    token, session = gate.issue()
    with TestClient(preview.app, base_url='https://testserver') as web:
        assert put(web).status_code == 401
        web.cookies.set(COOKIE, token)
        web.headers['X-CAD-CSRF'] = session['csrf']
        web.headers['Origin'] = 'https://testserver'
        assert web.post('/projects/dripper/api/uploads', headers={'Origin': 'https://evil.test'}).status_code == 403
        row = put(web, data=b'x'*300000).json()  # Above normal CAD JSON body bound.
        assert 'id' in row, row
        assert len(web.get('/projects/dripper/api/uploads').json()['uploads']) == 1
        path = f'/projects/dripper/downloads/uploads/{row["id"]}/file'
        assert web.get(path, headers={'Range': 'bytes=0-9'}).content == b'x'*10
        assert web.head(path).headers['content-length'] == '300000'
        api = f'/projects/dripper/api/uploads/{row["id"]}'
        assert web.patch(api, json={'note': 'New note', 'version': 1}).status_code == 200
        assert web.delete(api).status_code == 204
        assert web.get(path).status_code == 404
        assert web.get('/api/uploads').status_code == 404
        web.cookies.clear()
        assert web.get(path, follow_redirects=False).status_code == 303
