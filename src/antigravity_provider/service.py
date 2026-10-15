"""One chat request end to end: credentials, model routing, transport, response conversion."""

from __future__ import annotations

import threading
from typing import Any, Callable, Iterator, TypeVar

from .auth import CredentialManager
from .catalog import CatalogManager, ModelCatalog, catalog_manager
from .client import AntigravityClient
from .credentials import Credentials
from .errors import AntigravityError, TokenExpired
from .request import ChatRequest, build_generate_content_request, parse_chat_request
from .response import collect_response, to_openai_completion, to_openai_stream_chunks

T = TypeVar("T")


class AntigravityService:
    def __init__(
        self,
        *,
        credentials: CredentialManager | None = None,
        client: AntigravityClient | None = None,
        catalogs: CatalogManager | None = None,
    ) -> None:
        self.credentials = credentials or CredentialManager()
        self.client = client or AntigravityClient()
        self.catalogs = catalogs or catalog_manager

    def _with_token(self, credentials: Credentials, call: Callable[[Credentials], T]) -> T:
        """Run ``call``; on a 401 refresh the credential once and retry."""
        try:
            return call(credentials)
        except TokenExpired:
            return call(self.credentials.refresh(credentials))

    def catalog(self, *, force: bool = False, credentials: Credentials | None = None) -> ModelCatalog:
        credentials = credentials or self.credentials.current()

        def fetch() -> dict[str, Any]:
            return self._with_token(
                credentials,
                lambda creds: self.client.fetch_available_models(
                    access_token=creds.access_token, project_id=creds.project_id
                )
            )

        return self.catalogs.get(project_id=credentials.project_id, fetch=fetch, force=force)

    def build_body(
        self, payload: dict[str, Any], *, session_id: str | None = None
    ) -> tuple[ChatRequest, dict[str, Any], Credentials]:
        try:
            request = parse_chat_request(payload)
        except ValueError as exc:
            raise AntigravityError(str(exc), status=400, error_type="invalid_request_error") from exc
        credentials = self.credentials.current()
        body = build_generate_content_request(
            request,
            project_id=credentials.project_id,
            session_id=session_id,
            catalog=self.catalog(credentials=credentials),
        )
        return request, body, credentials

    def complete(self, payload: dict[str, Any], *, session_id: str | None = None) -> dict[str, Any]:
        request, body, credentials = self.build_body(payload, session_id=session_id)

        def generate(creds: Credentials) -> dict[str, Any]:
            return collect_response(self.client.stream_generate(access_token=creds.access_token, body=body))

        return to_openai_completion(request.model, self._with_token(credentials, generate))

    def stream(self, payload: dict[str, Any], *, session_id: str | None = None) -> Iterator[dict[str, Any]]:
        """OpenAI stream chunks. Request setup errors raise here, before iteration starts."""
        request, body, credentials = self.build_body(payload, session_id=session_id)
        return to_openai_stream_chunks(request.model, self._upstream(body, credentials))

    def _upstream(self, body: dict[str, Any], credentials: Credentials) -> Iterator[dict[str, Any]]:
        emitted = False
        try:
            for event in self.client.stream_generate(access_token=credentials.access_token, body=body):
                emitted = True
                yield event
        except TokenExpired:
            if emitted:
                raise
            refreshed = self.credentials.refresh(credentials)
            yield from self.client.stream_generate(access_token=refreshed.access_token, body=body)


_default_service: AntigravityService | None = None
_default_lock = threading.Lock()


def default_service() -> AntigravityService:
    global _default_service
    with _default_lock:
        if _default_service is None:
            _default_service = AntigravityService()
        return _default_service
