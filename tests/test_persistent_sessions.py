import hashlib
import json
import stat

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cad.auth import COOKIE, RENEW_INTERVAL, TTL, PasswordGate, PasswordMiddleware, password_hash


def scope(token):
    return {"type": "http", "headers": [(b"cookie", f"{COOKIE}={token}".encode())]}


def test_restart_revocation_and_private_hashed_store(tmp_path):
    path = tmp_path / "private" / "sessions.sqlite3"
    record = password_hash("test only")
    a = PasswordGate(record, path)
    token, session = a.issue()
    b = PasswordGate(record, path)
    assert b.session(scope(token)) == session
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert token.encode() not in path.read_bytes()
    assert hashlib.sha256(token.encode()).hexdigest().encode() in path.read_bytes()
    b.revoke(token)
    assert a.session(scope(token)) is None
    assert PasswordGate(record, path).session(scope(token)) is None


def test_password_change_revokes_all_and_old_workers_cannot_reissue(tmp_path):
    import pytest

    path = tmp_path / "sessions.sqlite3"
    record = password_hash("test old")
    old = PasswordGate(record, path)
    token, _ = old.issue()
    changed = PasswordGate(password_hash("test new"), path)
    assert changed.session(scope(token)) is None
    assert old.session(scope(token)) is None
    with pytest.raises(RuntimeError, match="credentials changed"):
        old.issue()
    assert PasswordGate(record, path).session(scope(token)) is None


def test_rolling_cookie_persists_and_expired_sessions_stay_dead(tmp_path, monkeypatch):
    now = [1_800_000_000.0]
    monkeypatch.setattr("cad.auth.time.time", lambda: now[0])
    record = password_hash("test only")
    path = tmp_path / "sessions.sqlite3"
    gate = PasswordGate(record, path)
    token, original = gate.issue()
    app = FastAPI()
    app.state.gate = gate
    app.add_middleware(PasswordMiddleware, owner=app)

    @app.get("/api/state")
    def state():
        return {"ok": True}

    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set(COOKIE, token)
        assert "set-cookie" not in client.get("/api/state").headers
        now[0] += RENEW_INTERVAL + 1
        bad = client.post("/auth/logout", headers={"Origin": "https://evil.invalid"})
        assert bad.status_code == 403 and "set-cookie" not in bad.headers
        assert gate.session(scope(token))["expires"] == original["expires"]
        response = client.get("/auth/session")
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        for value in ["Secure", "HttpOnly", "SameSite=strict", "Path=/", f"Max-Age={TTL}"]:
            assert value in cookie
        assert response.json()["expires"] == now[0] + TTL
        restarted = PasswordGate(record, path)
        assert restarted.session(scope(token))["expires"] == now[0] + TTL
        now[0] += TTL + 1
        assert client.get("/api/state").status_code == 401
        assert restarted.session(scope(token)) is None
        assert not restarted.renew(scope(token), response.json() | {"renewed": 0})


def test_persistent_store_bounded_and_env_configuration(tmp_path, monkeypatch):
    record = password_hash("test only")
    password_file = tmp_path / "password.json"
    password_file.write_text(json.dumps(record))
    monkeypatch.setenv("CAD_PASSWORD_HASH_FILE", str(password_file))
    monkeypatch.setenv("CAD_SESSION_DB", str(tmp_path / "sessions.sqlite3"))
    gate = PasswordGate.from_env()
    first, _ = gate.issue()
    for _ in range(128):
        latest, _ = gate.issue()
    assert gate.session(scope(first)) is None
    assert PasswordGate.from_env().session(scope(latest)) is not None
    with gate.store.connection() as db:
        assert db.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 128


def test_successful_download_renews_but_logout_never_resurrects(tmp_path, monkeypatch):
    now = [1_800_000_000.0]
    monkeypatch.setattr("cad.auth.time.time", lambda: now[0])
    gate = PasswordGate(password_hash("test only"), tmp_path / "sessions.sqlite3")
    token, session = gate.issue()
    app = FastAPI()
    app.state.gate = gate
    app.add_middleware(PasswordMiddleware, owner=app)

    @app.get("/download")
    def download():
        return {"ok": True}

    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set(COOKIE, token)
        now[0] += RENEW_INTERVAL + 1
        assert "set-cookie" in client.get("/download").headers
        now[0] += RENEW_INTERVAL + 1
        response = client.post(
            "/auth/logout",
            headers={
                "Origin": "https://testserver",
                "X-CAD-CSRF": session["csrf"],
            },
        )
        assert response.status_code == 200
        assert len(response.headers.get_list("set-cookie")) == 1
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert gate.session(scope(token)) is None
        assert not gate.renew(scope(token), session)
