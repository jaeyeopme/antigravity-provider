from __future__ import annotations


class AntigravityError(Exception):
    """Provider failure carrying an HTTP-like status for Hermes retry/fallback classification."""

    def __init__(self, message: str, *, status: int = 500, error_type: str = "api_error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_type = error_type

    @property
    def status_code(self) -> int:
        return self.status


class TokenExpired(AntigravityError):
    def __init__(self, message: str = "Antigravity access token expired"):
        super().__init__(message, status=401, error_type="invalid_request_error")
