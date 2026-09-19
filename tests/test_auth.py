import time

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cad.auth import COOKIE, PasswordGate, PasswordMiddleware, password_hash

PASSWORD = "a-test-password-not-for-production"


@pytest.fixture
def protected():
    app = FastAPI()
    app.state.gate = PasswordGate(password_hash(PASSWORD))
    app.add_middleware(PasswordMiddleware, owner=app)

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST"])
    def private(path: str):
        return {"secret": "private workspace content"}

    @app.websocket("/api/events")
    async def events(socket: WebSocket):
        await socket.accept()
        await socket.send_json({"secret": True})

    with TestClient(app, base_url="https://testserver") as client:
        yield client, app.state.gate


def login(client):
    return client.post(
        "/auth/login",
        data={"password": PASSWORD},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )


def test_all_content_is_locked_and_configuration_fails_closed(protected):
    client, gate = protected
    for path in ["/", "/api/state", "/api/agent/state", "/downloads/latest.zip", "/assets/app.js"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code in (401, 303)
        assert "private workspace content" not in response.text
        assert response.headers["cache-control"] == "no-store"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "wss://testserver/api/events", headers={"Origin": "https://testserver"}
        ):
            pass
    gate.record = None
    assert client.get("/api/state").status_code == 503


def test_password_cookie_csrf_logout_and_expiry(protected):
    client, gate = protected
    assert client.post("/auth/login", data={"password": PASSWORD}).status_code == 403
    assert (
        client.post(
            "/auth/login", data={"password": "wrong"}, headers={"Origin": "https://testserver"}
        ).status_code
        == 401
    )
    response = login(client)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert (
        COOKIE in cookie
        and "HttpOnly" in cookie
        and "Secure" in cookie
        and "SameSite=strict" in cookie
    )
    assert client.get("/api/state").status_code == 200
    csrf = client.get("/auth/session").json()["csrf"]
    assert client.post("/api/agent/prompt", json={}).status_code == 403
    assert (
        client.post(
            "/api/agent/prompt",
            json={},
            headers={"Origin": "https://evil.invalid", "X-CAD-CSRF": csrf},
        ).status_code
        == 403
    )
    headers = {"Origin": "https://testserver", "X-CAD-CSRF": csrf}
    assert client.post("/api/agent/prompt", json={}, headers=headers).status_code == 200
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "wss://testserver/api/events", headers={"Origin": "https://evil.invalid"}
        ):
            pass
    with client.websocket_connect(
        "wss://testserver/api/events", headers={"Origin": "https://testserver"}
    ) as socket:
        assert socket.receive_json() == {"secret": True}
    old_cookie = client.cookies.get(COOKIE)
    assert client.post("/auth/logout", headers=headers).status_code == 200
    client.cookies.set(COOKIE, old_cookie)
    assert client.get("/api/state").status_code == 401
    client.cookies.clear()
    login(client)
    for record in gate.sessions.values():
        record["expires"] = time.time() - 1
    assert client.get("/api/state").status_code == 401


def test_login_rate_limit_body_limit_and_safe_redirect(protected):
    client, gate = protected
    headers = {"Origin": "https://testserver"}
    assert client.post("/auth/login", content=b"x" * 5000, headers=headers).status_code == 413
    response = client.post(
        "/auth/login?next=//evil.invalid",
        data={"password": PASSWORD},
        headers=headers,
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"
    gate.attempts.extend([time.monotonic()] * 12)
    assert (
        client.post("/auth/login", data={"password": PASSWORD}, headers=headers).status_code == 429
    )
