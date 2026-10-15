"""OpenAI-client-shaped facade that Hermes drives, backed by AntigravityService."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any, Iterator

from .service import AntigravityService, default_service

_END = object()
# Fields the OpenAI SDK exposes as plain dicts; Hermes reads them as dicts (e.g. the Gemini
# thought signature in a tool call's ``extra_content``), so they must not become namespaces.
_DICT_FIELDS = {"extra_content"}


def _namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{
            key: nested if key in _DICT_FIELDS else _namespace(nested) for key, nested in value.items()
        })
    if isinstance(value, list):
        return [_namespace(nested) for nested in value]
    return value


def openai_completion_object(completion: dict[str, Any]) -> SimpleNamespace:
    """Attribute access like the OpenAI SDK, with the optional fields Hermes reads always present."""
    completion = dict(completion)
    choices = []
    for raw_choice in completion.get("choices") or []:
        choice = dict(raw_choice)
        message = dict(choice.get("message") or {})
        message.setdefault("content", None)
        message.setdefault("tool_calls", None)
        choice["message"] = message
        choices.append(choice)
    completion["choices"] = choices
    completion.setdefault("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    return _namespace(completion)


class ChunkStream:
    """Sync and async iterator over stream chunks that any thread may close, even mid-read.

    Hermes closes streams from interrupt handlers while a worker thread is blocked reading the
    next chunk. Closing a generator that is executing raises, so the close waits for the
    in-flight read on a background thread instead; the HTTP response closes with the generator.
    """

    def __init__(self, chunks: Iterator[dict[str, Any]]) -> None:
        self._chunks = chunks
        self._running = threading.Lock()
        self._closed = False

    def __iter__(self) -> "ChunkStream":
        return self

    def __next__(self) -> Any:
        with self._running:
            if self._closed:
                raise StopIteration
            return _namespace(next(self._chunks))

    def __aiter__(self) -> "ChunkStream":
        return self

    async def __anext__(self) -> Any:
        value = await asyncio.to_thread(next, self, _END)
        if value is _END:
            raise StopAsyncIteration
        return value

    def close(self) -> None:
        self._closed = True
        if self._running.acquire(blocking=False):
            try:
                self._chunks.close()
            finally:
                self._running.release()
        else:
            threading.Thread(target=self._close_when_idle, name="antigravity-stream-close", daemon=True).start()

    def _close_when_idle(self) -> None:
        with self._running:
            self._chunks.close()

    async def aclose(self) -> None:
        self.close()

    def __enter__(self) -> "ChunkStream":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _DeferredCompletion:
    """Result of ``create()`` called while an event loop is running.

    Hermes awaits it on async paths; sync callers on the loop thread use it directly.
    Either way the blocking request runs once.
    """

    def __init__(self, client: "HermesAntigravityClient", payload: dict[str, Any], stream: bool, session_id: str | None):
        self._client = client
        self._args = (payload, stream, session_id)
        self._value: Any = _END
        self._lock = threading.Lock()

    def _resolve(self) -> Any:
        with self._lock:
            if self._value is _END:
                self._value = self._client._complete(*self._args)
        return self._value

    def __await__(self):
        return asyncio.to_thread(self._resolve).__await__()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __iter__(self):
        return iter(self._resolve())

    def __next__(self) -> Any:
        return next(self._resolve())


class HermesAntigravityClient:
    """Returned by ``ProviderProfile.create_client``; Hermes calls ``chat.completions.create``."""

    HERMES_SKIP_TRANSPORT_WRAP = True
    HERMES_SKIP_ASYNC_WRAP = True

    def __init__(self, *, api_key: str = "", base_url: str = "", service: AntigravityService | None = None, **_: Any):
        self.api_key = api_key
        self.base_url = base_url
        self.is_closed = False
        self._service = service
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @property
    def service(self) -> AntigravityService:
        return self._service or default_service()

    def close(self) -> None:
        self.is_closed = True

    def _create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]] | None = None,
        stream: bool = False,
        _antigravity_session_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        payload = {"model": model, "messages": messages or [], **kwargs}
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._complete(payload, stream, _antigravity_session_id)
        return _DeferredCompletion(self, payload, stream, _antigravity_session_id)

    def _complete(self, payload: dict[str, Any], stream: bool, session_id: str | None) -> Any:
        if stream:
            return ChunkStream(self.service.stream(payload, session_id=session_id))
        return openai_completion_object(self.service.complete(payload, session_id=session_id))
