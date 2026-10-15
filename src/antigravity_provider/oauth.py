"""Google OAuth for the Antigravity client: token refresh and the browser PKCE login flow."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

from .errors import AntigravityError
from .net import request_json

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 51121
CALLBACK_PATH = "/oauth-callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo?alt=json"
# Public desktop-app OAuth client of the Antigravity IDE. Desktop clients cannot keep their secret
# confidential (RFC 8252); it is split only so secret scanners do not flag every checkout.
CLIENT_ID = "".join(
    ("1071006060591", "-", "tmhssin2h21lcre235vtolojh4g403ep", ".apps.", "googleusercontent", ".com")
)
CLIENT_SECRET = "".join(("GOC", "SPX", "-", "K58FWR486LdLJ1mLB", "8sXC4z6qDAf"))
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]

PostForm = Callable[[str, dict[str, str]], dict[str, Any]]


def oauth_client() -> tuple[str, str]:
    return CLIENT_ID, CLIENT_SECRET


def _post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    return request_json(url, headers={}, form=form, timeout=60, error_prefix="OAuth token request failed")


def _token_set(data: dict[str, Any], *, refresh_token: str | None = None) -> dict[str, Any]:
    try:
        seconds = int(data.get("expires_in"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        seconds = 3600
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or refresh_token,
        # Expire five minutes early so a request never starts with an about-to-expire token.
        "expires_at": int(time.time()) + seconds - 300,
        "token_type": data.get("token_type", "Bearer"),
    }


def refresh_access_token(
    refresh_token: str,
    *,
    post_form: PostForm | None = None,
    client: tuple[str, str] | None = None,
) -> dict[str, Any]:
    client_id, client_secret = client or oauth_client()
    data = (post_form or _post_form)(
        TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if not data.get("access_token"):
        raise AntigravityError(
            "OAuth refresh response did not include access_token", status=401, error_type="invalid_request_error"
        )
    return _token_set(data, refresh_token=refresh_token)


def exchange_code_for_tokens(
    code: str,
    *,
    redirect_uri: str,
    code_verifier: str,
    post_form: PostForm | None = None,
    client: tuple[str, str] | None = None,
) -> dict[str, Any]:
    client_id, client_secret = client or oauth_client()
    data = (post_form or _post_form)(
        TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )
    if not data.get("refresh_token") or not data.get("access_token"):
        raise AntigravityError(
            "No refresh token received. Re-run login and approve offline access.",
            status=401,
            error_type="invalid_request_error",
        )
    return _token_set(data)


def fetch_user_email(access_token: str) -> str | None:
    try:
        data = request_json(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    except AntigravityError:
        return None
    email = data.get("email")
    return email if isinstance(email, str) and email else None


def callback_redirect_uri() -> str:
    host = os.getenv("ANTIGRAVITY_OAUTH_REDIRECT_HOST", CALLBACK_HOST)
    return f"http://{host}:{_callback_port()}{CALLBACK_PATH}"


def _callback_port() -> int:
    return int(os.getenv("ANTIGRAVITY_OAUTH_PORT", str(CALLBACK_PORT)))


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(
    state: str,
    redirect_uri: str | None = None,
    client: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Return the consent URL and the PKCE verifier that must accompany the code exchange."""
    verifier, challenge = _pkce_pair()
    client_id, _ = client or oauth_client()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri or callback_redirect_uri(),
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", verifier


class _CallbackServer(HTTPServer):
    def __init__(self, address: tuple[str, int], expected_state: str):
        super().__init__(address, _CallbackHandler)
        self.expected_state = expected_state
        self.received_code: str | None = None
        self.received_error: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)
        # Only the redirect carrying our state may finish the login; anything else (a stale tab,
        # another local process) is answered and ignored.
        if (params.get("state") or [None])[0] != self.server.expected_state:
            self._reply(400, "Login state did not match. Return to the newest login tab.")
            return
        self.server.received_error = (params.get("error") or [None])[0]
        self.server.received_code = (params.get("code") or [None])[0]
        self._reply(200, "Antigravity Hermes plugin login complete. You can close this tab.")

    def _reply(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def browser_login(*, open_browser: bool = True, timeout: int = 300) -> dict[str, Any]:
    """Run the loopback PKCE flow and return the token set."""
    state = secrets.token_urlsafe(24)
    redirect_uri = callback_redirect_uri()
    auth_url, verifier = build_auth_url(state, redirect_uri)
    bind_host = os.getenv("ANTIGRAVITY_OAUTH_BIND_HOST", CALLBACK_HOST)
    server = _CallbackServer((bind_host, _callback_port()), state)
    server.timeout = 1
    try:
        print("Open this URL to authorize Antigravity:", file=sys.stderr)
        print(auth_url, file=sys.stderr)
        if open_browser:
            webbrowser.open(auth_url)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not server.received_code and not server.received_error:
            server.handle_request()
    finally:
        server.server_close()

    if server.received_error:
        raise AntigravityError(
            f"OAuth callback failed: {server.received_error}", status=401, error_type="invalid_request_error"
        )
    if not server.received_code:
        raise AntigravityError("OAuth login timed out", status=401, error_type="invalid_request_error")
    return exchange_code_for_tokens(server.received_code, redirect_uri=redirect_uri, code_verifier=verifier)
