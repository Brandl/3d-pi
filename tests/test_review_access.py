from test_preview_downloads import REVISION, gateway as gateway_fixture

gateway = gateway_fixture


def test_inspection_images_require_login_and_publication(gateway):
    client, _ = gateway
    path = f"/api/revisions/{REVISION}/artifacts/review-iso.png"
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert "attachment" not in response.headers.get("content-disposition", "")
    assert client.get(f"/api/revisions/{'b' * 32}/artifacts/review-iso.png").status_code == 404
    client.cookies.clear()
    assert client.get(path).status_code == 401
