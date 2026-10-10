import urllib.request

from cad import preview
from cad.projects import project_id
from test_preview_downloads import REVISION, gateway as gateway_fixture

gateway = gateway_fixture


def test_registered_old_output_named_download_and_scope(gateway, monkeypatch):
    client, payload = gateway
    previous = preview.upstream
    download = preview.urllib.request.urlopen
    asset_id = "c" * 32

    def metadata(path):
        if path == "/api/state":
            return {
                "revision": None,
                "generation": 0,
                "publications": [],
                "history": [],
                "workspace": {
                    "commits": [],
                    "assets": [
                        dict(
                            id=asset_id,
                            revision=REVISION,
                            name="Return fixture",
                            role="test",
                            note="Check the retaining ledge before printing.",
                        )
                    ]
                    if project_id.get() == "dripper"
                    else [],
                },
            }
        return previous(path)

    def scoped_download(request, timeout):
        return download(
            urllib.request.Request(
                request.full_url.replace("/projects/dripper", ""),
                method=request.get_method(),
                headers=dict(request.header_items()),
            ),
            timeout,
        )

    monkeypatch.setattr(preview, "upstream", metadata)
    monkeypatch.setattr(preview.urllib.request, "urlopen", scoped_download)
    path = f"/projects/dripper/downloads/sets/{asset_id}/zip:casting_box"
    response = client.get(path)
    assert response.status_code == 200 and response.content == payload
    assert "Return-fixture-zip-casting_box.zip" in response.headers["content-disposition"]
    assert client.head(path).status_code == 200
    assert client.get(path, headers={"Range": "bytes=0-9"}).content == payload[:10]
    assert client.get(path.replace("/dripper/", "/other/")).status_code == 404
    assert client.get(path.replace("/projects/dripper", "")).status_code == 404
    assert client.get(path.replace("zip:casting_box", "document.json")).status_code == 404
    instructions = path.replace("zip:casting_box", "instructions.txt")
    assert client.get(instructions).text == "Check the retaining ledge before printing."
    assert client.head(instructions).content == b""
    client.cookies.clear()
    assert client.get(path, follow_redirects=False).status_code == 303
    assert client.get(f"/projects/dripper/api/revisions/{REVISION}").status_code == 401


def test_live_previews_and_cursor_remain_project_scoped(gateway, monkeypatch):
    client, _ = gateway
    data = dict(
        revision=None,
        generation=0,
        publications=[],
        workspace=None,
        history=[dict(id=REVISION, status="ready", name="Synthetic preview", valid=True)],
        intermediates=[dict(revision=REVISION, name="Synthetic preview", created=1)],
        event_sequence=123,
    )
    previous = preview.upstream
    monkeypatch.setattr(
        preview, "upstream", lambda path: data if path == "/api/state" else previous(path)
    )
    scoped = client.get("/projects/dripper/api/state").json()
    assert scoped["intermediates"] == data["intermediates"]
    assert scoped["event_sequence"] == 123 and scoped["history"][0]["valid"] is True
    public = client.get("/api/state").json()
    assert public["intermediates"] == [] and public["event_sequence"] == 0
    assert public["history"] == []
    data["history"] = []  # Last good preview can outlive the 100-build history window.
    token = project_id.set("dripper")
    try:
        assert preview.published(REVISION)["result"]["exports"]
    finally:
        project_id.reset(token)
    assert client.get(f"/api/revisions/{REVISION}").status_code == 404
    client.cookies.clear()
    assert client.get("/projects/dripper/api/state").status_code == 401
