import io
import urllib.error
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient

from cad import preview
from cad.auth import PasswordGate, COOKIE

REVISION = "a" * 32


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "published CAD parts")
    payload = buffer.getvalue()
    file = tmp_path / "casting-box.zip"
    file.write_bytes(payload)
    upstream_app = FastAPI()

    @upstream_app.api_route(
        "/api/revisions/{revision}/artifacts/{filename}", methods=["GET", "HEAD"]
    )
    def download(revision: str, filename: str):
        assert revision == REVISION
        if filename == "review-iso.png":
            image = tmp_path / "review-iso.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            return FileResponse(image, media_type="image/png")
        assert filename == "casting-box.zip"
        return FileResponse(file, filename=filename)

    @upstream_app.api_route("/api/revisions/{revision}/sections/{section_id}/{filename}", methods=["GET", "HEAD"])
    def section_download(revision: str, section_id: str, filename: str):
        assert revision == REVISION and section_id == "c" * 64
        assert filename == "section.dxf"
        return FileResponse(file, filename=filename)

    origin = TestClient(upstream_app)

    def metadata(path):
        if path == "/api/state":
            return {"revision": REVISION, "publications": [{"revision": REVISION}]}
        assert path == f"/api/revisions/{REVISION}"
        return {"result": {"exports": {"zip:casting_box": "casting-box.zip"}}}

    def urlopen(request, timeout):
        assert request.full_url.startswith(preview.ORIGIN + "/api/revisions/")
        response = origin.request(
            request.get_method(),
            request.full_url.removeprefix(preview.ORIGIN),
            headers=dict(request.header_items()),
        )
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                response.status_code,
                "upstream error",
                response.headers,
                io.BytesIO(response.content),
            )

        class Wrapped:
            status = response.status_code
            headers = response.headers

            def read(self):
                return response.content

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return Wrapped()

    monkeypatch.setattr(preview, "upstream", metadata)
    monkeypatch.setattr(preview.urllib.request, "urlopen", urlopen)
    gate = PasswordGate({"salt": "00" * 16, "hash": "00" * 64})
    monkeypatch.setattr(preview.app.state, "gate", gate)
    token, _ = gate.issue()
    with TestClient(preview.app, base_url="https://testserver", cookies={COOKIE: token}) as client:
        yield client, payload
    origin.close()


@pytest.mark.parametrize(
    "path",
    [
        f"/api/revisions/{REVISION}/artifacts/casting-box.zip",
        f"/downloads/{REVISION}/casting-box.zip",
        "/downloads/latest.zip",
    ],
)
def test_download_head_ranges_and_filename(gateway, path):
    client, payload = gateway
    response = client.get(path)
    assert response.status_code == 200 and response.content == payload
    assert "attachment" in response.headers["content-disposition"]
    assert "casting-box.zip" in response.headers["content-disposition"]
    head = client.head(path)
    assert head.status_code == 200 and head.content == b""
    assert int(head.headers["content-length"]) == len(payload)
    assert head.headers["accept-ranges"] == "bytes"
    assert head.headers["x-cad-revision"] == REVISION
    partial = client.get(path, headers={"Range": "bytes=0-15"})
    assert partial.status_code == 206 and partial.content == payload[:16]
    assert partial.headers["content-range"] == f"bytes 0-15/{len(payload)}"
    remainder = client.get(path, headers={"Range": "bytes=16-", "If-Range": head.headers["etag"]})
    assert remainder.status_code == 206 and partial.content + remainder.content == payload
    invalid = client.get(path, headers={"Range": "bytes=999999-"})
    assert invalid.status_code == 416
    if path.endswith("latest.zip"):
        assert head.headers["cache-control"] == "no-store"


def test_section_download_auth_ranges_and_whitelist(gateway):
    client, payload = gateway
    path = f"/downloads/{REVISION}/sections/{'c' * 64}/section.dxf"
    assert client.get(path).content == payload
    assert client.head(path).content == b""
    assert client.get(path, headers={"Range": "bytes=0-7"}).status_code == 206
    assert client.get(path.replace("section.dxf", "input.json")).status_code == 404
    assert client.get(path.replace(REVISION, "b" * 32)).status_code == 404
    client.cookies.clear()
    assert client.get(path, follow_redirects=False).status_code in (401, 303)


def test_only_published_exports_and_no_mutation(gateway):
    client, _ = gateway
    assert client.get(f"/downloads/{'b' * 32}/casting-box.zip").status_code == 404
    assert client.head(f"/downloads/{REVISION}/document.json").status_code == 404
    csrf = client.get("/auth/session").json()["csrf"]
    assert (
        client.post(
            "/downloads/latest.zip", headers={"Origin": "https://testserver", "X-CAD-CSRF": csrf}
        ).status_code
        == 405
    )
