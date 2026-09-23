"""Single-owner website login. Fail closed when no password hash is configured."""

import asyncio
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from cad.sessions import SessionStore

COOKIE = "__Host-cad_session"
TTL = 365 * 24 * 3600
RENEW_INTERVAL = 24 * 3600


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=128 * 1024 * 1024
    )
    return {"salt": salt, "hash": value.hex()}


class PasswordGate:
    def __init__(self, record=None, session_path=None):
        self.record = record
        credential = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        self.store = SessionStore(session_path, credential) if session_path else None
        self.sessions = {}
        self.attempts = deque()
        self.verify_lock = asyncio.Lock()

    @classmethod
    def from_env(cls):
        path = os.environ.get("CAD_PASSWORD_HASH_FILE")
        return cls(
            json.loads(Path(path).read_text()) if path else None,
            session_path=os.environ.get("CAD_SESSION_DB"),
        )

    def session(self, scope):
        request = Request({**scope, "type": "http"})
        token = request.cookies.get(COOKIE, "")
        if len(token) != 43:
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        session = self.store.get(key, time.time()) if self.store else self.sessions.get(key)
        if session and session["expires"] > time.time():
            return session
        self.sessions.pop(key, None)
        return None

    def issue(self):
        now = time.time()
        self.sessions = {k: v for k, v in self.sessions.items() if v["expires"] > now}
        if len(self.sessions) >= 128:
            self.sessions.pop(next(iter(self.sessions)))
        token = secrets.token_urlsafe(32)
        session = {"csrf": secrets.token_urlsafe(32), "expires": now + TTL, "renewed": now}
        key = hashlib.sha256(token.encode()).hexdigest()
        if self.store:
            self.store.put(key, session, now)
        else:
            self.sessions[key] = session
        return token, session

    def renew(self, scope, session):
        now = time.time()
        if not session or now - session["renewed"] < RENEW_INTERVAL:
            return False
        token = Request({**scope, "type": "http"}).cookies.get(COOKIE, "")
        key = hashlib.sha256(token.encode()).hexdigest()
        if self.store and not self.store.renew(key, now, TTL, RENEW_INTERVAL):
            return False
        if session["expires"] <= now:
            return False
        session.update(expires=now + TTL, renewed=now)
        return True

    def revoke(self, token):
        key = hashlib.sha256(token.encode()).hexdigest()
        if self.store:
            self.store.revoke(key)
        self.sessions.pop(key, None)


def same_origin(request):
    origin = request.headers.get("origin", "")
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and parsed.netloc == request.headers.get("host")


def safe_next(value):
    # Only local absolute paths, never scheme-relative redirects or backslashes.
    return (
        value
        if value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not any(ord(c) < 32 for c in value)
        else "/"
    )


class PasswordMiddleware:
    def __init__(self, app, owner):
        self.app, self.owner = app, owner

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        gate = self.owner.state.gate
        request = Request({**scope, "type": "http"}, receive)
        session = gate.session(scope)
        if scope["type"] == "websocket":
            if not session or not same_origin(request):
                return await send({"type": "websocket.close", "code": 4401})
            return await self.app(scope, receive, send)

        renew_cookie = False

        async def secured_send(message):
            if message["type"] == "http.response.start":
                if (
                    session
                    and gate.record is not None
                    and scope["path"] not in ("/auth/login", "/auth/logout")
                    and message["status"] < 400
                    and (renew_cookie or gate.renew(scope, session))
                ):
                    cookie = Response()
                    cookie.set_cookie(
                        COOKIE,
                        request.cookies[COOKIE],
                        max_age=TTL,
                        httponly=True,
                        secure=True,
                        samesite="strict",
                        path="/",
                    )
                    message["headers"] = list(message.get("headers", [])) + [
                        (key, value) for key, value in cookie.raw_headers if key == b"set-cookie"
                    ]
                security = [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"same-origin"),
                    (b"x-frame-options", b"DENY"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                    ),
                    (b"strict-transport-security", b"max-age=31536000"),
                ]
                keys = {key for key, _ in security}
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in keys
                ] + security
            await send(message)

        async def reply(response):
            await response(scope, receive, secured_send)

        if gate.record is None:
            return await reply(
                JSONResponse({"detail": "Website locked: password has not been configured"}, 503)
            )
        path = scope["path"]
        if path == "/auth/login":
            target = safe_next(request.query_params.get("next", "/"))
            if request.method == "GET":
                page = Path(__file__).with_name("login.html").read_text(encoding="utf-8")
                return await reply(
                    HTMLResponse(
                        page.replace(
                            "{{ACTION}}",
                            html.escape("/auth/login?next=" + quote(target, safe=""), quote=True),
                        )
                    )
                )
            if request.method != "POST":
                return await reply(JSONResponse({"detail": "Method not allowed"}, 405))
            if not same_origin(request):
                return await reply(JSONResponse({"detail": "Origin rejected"}, 403))
            now = time.monotonic()
            while gate.attempts and gate.attempts[0] < now - 60:
                gate.attempts.popleft()
            # Global bound cannot be bypassed by spoofing forwarded IP headers.
            if len(gate.attempts) >= 12:
                return await reply(
                    JSONResponse(
                        {"detail": "Too many login attempts. Try again in a minute."},
                        429,
                        headers={"Retry-After": "60"},
                    )
                )
            gate.attempts.append(now)
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 4096:
                            return await reply(JSONResponse({"detail": "Request too large"}, 413))
            except TimeoutError:
                return await reply(JSONResponse({"detail": "Request timed out"}, 408))
            try:
                password = parse_qs(body.decode("utf-8")).get("password", [""])[0]
            except (UnicodeDecodeError, ValueError):
                password = ""
            async with gate.verify_lock:
                check = await asyncio.to_thread(password_hash, password, gate.record["salt"])
            if not hmac.compare_digest(check["hash"], gate.record["hash"]):
                return await reply(
                    HTMLResponse(
                        '<h1>Incorrect password</h1><p><a href="/auth/login">Try again</a></p>', 401
                    )
                )
            token, _ = gate.issue()
            response = RedirectResponse(target, 303)
            response.set_cookie(
                COOKIE, token, max_age=TTL, httponly=True, secure=True, samesite="strict", path="/"
            )
            return await reply(response)
        if not session:
            response = JSONResponse({"detail": "Login required"}, 401)
            if request.method in ("GET", "HEAD") and not path.startswith("/api/"):
                target = scope.get("cad_original_path", path) + (
                    "?" + scope["query_string"].decode("utf-8", errors="replace")
                    if scope.get("query_string")
                    else ""
                )
                response = RedirectResponse("/auth/login?next=" + quote(target, safe=""), 303)
            return await reply(response)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not same_origin(request) or not hmac.compare_digest(
                request.headers.get("x-cad-csrf", ""), session["csrf"]
            ):
                return await reply(JSONResponse({"detail": "CSRF check failed"}, 403))
        if path == "/auth/session" and request.method == "GET":
            renew_cookie = gate.renew(scope, session)
            return await reply(
                JSONResponse({"csrf": session["csrf"], "expires": session["expires"]})
            )
        if path == "/auth/logout" and request.method == "POST":
            token = request.cookies.get(COOKIE, "")
            gate.revoke(token)
            response = JSONResponse({"ok": True})
            response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
            return await reply(response)
        return await self.app(scope, receive, secured_send)


if __name__ == "__main__":
    import argparse
    import getpass

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    password = (
        secrets.token_urlsafe(24) if args.generate else getpass.getpass("New website password: ")
    )
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters")
    if not args.generate and password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords differ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(password_hash(password), handle)
    os.chmod(args.output, 0o600)
    if args.generate:
        print(password)
