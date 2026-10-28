"""Which credential a request uses, and keeping it fresh.

Browser OAuth saved in the active Hermes profile is an explicit override. Otherwise the `agy`
Keychain credential is used; it is read once per process and its refreshed token is kept in memory
(the Keychain item belongs to `agy` and is never written).
"""

from __future__ import annotations

import sys
import threading
from dataclasses import replace
from typing import Any, Callable

from . import oauth
from .cloudcode import load_or_onboard_project
from .credentials import (
    SOURCE_BROWSER,
    CredentialStore,
    Credentials,
    load_agy_keychain_credentials,
)
from .errors import AntigravityError, TokenExpired


class CredentialManager:
    def __init__(
        self,
        *,
        store_factory: Callable[[], CredentialStore] = CredentialStore.default,
        keychain_loader: Callable[[], Credentials | None] = load_agy_keychain_credentials,
        refresh_tokens: Callable[[str], dict[str, Any]] = oauth.refresh_access_token,
        discover_project: Callable[[str], str] = load_or_onboard_project,
        fetch_email: Callable[[str], str | None] = oauth.fetch_user_email,
    ) -> None:
        self._store_factory = store_factory
        self._keychain_loader = keychain_loader
        self._refresh_tokens = refresh_tokens
        self._discover_project = discover_project
        self._fetch_email = fetch_email
        self._lock = threading.Lock()
        self._keychain: Credentials | None = None
        self._keychain_loaded = False

    def store(self) -> CredentialStore:
        # Resolved per call so a Hermes profile switch picks up that profile's file.
        return self._store_factory()

    def current(self) -> Credentials:
        store = self.store()
        stored = store.load()
        if stored is not None:
            prepared = self._prepare(stored)
            if prepared != stored:
                store.save(prepared)
            return prepared

        with self._lock:
            if not self._keychain_loaded:
                self._keychain = self._keychain_loader()
                # A locked or unreadable Keychain is read again on the next request.
                self._keychain_loaded = self._keychain is not None
            if self._keychain is None or not self._keychain.usable:
                raise AntigravityError(
                    "Missing Antigravity credentials. Run `hermes agy login`.",
                    status=401,
                    error_type="invalid_request_error",
                )
            self._keychain = self._prepare_keychain(self._keychain)
            return self._keychain

    def refresh(self, rejected: Credentials) -> Credentials:
        """Replace a credential the backend rejected with 401."""
        if not rejected.refresh_token:
            raise TokenExpired()
        if rejected.source == SOURCE_BROWSER:
            store = self.store()
            latest = store.load()
            # Another Hermes process may already have refreshed and saved a newer token.
            if latest is None:
                return self.current()  # logged out or switched to Keychain meanwhile; don't re-save
            if latest.access_token and latest.access_token != rejected.access_token:
                return latest
            refreshed = latest.with_tokens(self._refresh_tokens(latest.refresh_token))
            store.save(refreshed)
            return refreshed
        with self._lock:
            cached = self._keychain
            if cached is not None and cached.access_token and cached.access_token != rejected.access_token:
                return cached  # another request already refreshed it
            refreshed = self._prepare_keychain(replace(rejected, access_token=""))
            self._keychain = refreshed
            return refreshed

    def _prepare_keychain(self, credentials: Credentials) -> Credentials:
        """``_prepare`` for the Keychain credential; call with the lock held."""
        try:
            return self._prepare(credentials)
        except AntigravityError:
            # `agy` may have signed in again since this process read the Keychain, revoking the
            # refresh token it read then.
            reloaded = self._keychain_loader()
            if reloaded is None or not reloaded.usable or reloaded.refresh_token == credentials.refresh_token:
                raise
            return self._prepare(reloaded)

    def _prepare(self, credentials: Credentials) -> Credentials:
        if credentials.needs_refresh():
            credentials = credentials.with_tokens(self._refresh_tokens(credentials.refresh_token))
        if not credentials.project_id:
            if not credentials.access_token:
                raise AntigravityError(
                    "Missing access token for Antigravity project discovery",
                    status=401,
                    error_type="invalid_request_error",
                )
            credentials = replace(credentials, project_id=self._discover_project(credentials.access_token))
        return credentials

    def login(self, *, use_keychain: bool = True, open_browser: bool = True, timeout: int = 300) -> Credentials:
        store = self.store()
        if use_keychain:
            keychain = self._keychain_loader()
            if keychain is not None and keychain.usable:
                try:
                    prepared = self._with_email(self._prepare(keychain))
                except AntigravityError as exc:
                    print(f"The agy Keychain credential did not work ({exc.message}); using browser sign-in.", file=sys.stderr)
                else:
                    store.delete()
                    with self._lock:
                        self._keychain, self._keychain_loaded = prepared, True
                    return prepared

        tokens = oauth.browser_login(open_browser=open_browser, timeout=timeout)
        credentials = Credentials.from_mapping(tokens, source=SOURCE_BROWSER)
        credentials = self._with_email(self._prepare(credentials))
        store.save(credentials)
        return credentials

    def logout(self) -> None:
        self.store().delete()

    def describe(self) -> dict[str, Any]:
        """Credential status without network calls or token refreshes."""
        stored = self.store().load()
        if stored is not None:
            credentials, source = stored, "browser OAuth"
        else:
            credentials = self._keychain_loader()
            source = "agy Keychain" if credentials is not None else "none"
        credentials = credentials or Credentials(source="")
        return {
            "source": source,
            "has_access_token": bool(credentials.access_token),
            "has_refresh_token": bool(credentials.refresh_token),
            "expires_at": credentials.expires_at,
            "project_id": credentials.project_id,
            "email": credentials.email,
        }

    def _with_email(self, credentials: Credentials) -> Credentials:
        email = self._fetch_email(credentials.access_token)
        return replace(credentials, email=email) if email else credentials

    def clear_cache(self) -> None:
        with self._lock:
            self._keychain, self._keychain_loaded = None, False

