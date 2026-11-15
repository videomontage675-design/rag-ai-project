"""Provider ports: what the pipeline may ask of a model provider, and how calls fail.

The pipeline depends on these Protocols only (STD-001 §4); adapters satisfy them without
inheriting from them. Failures are typed :class:`~rag_app.core.errors.AppError` subclasses, so
nothing above ``providers/`` ever sees an ``httpx`` exception (STD-001 §7), and the retry
logic can decide from ``retryable`` alone (DESIGN-001 §10).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Protocol

from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import EmbeddingTask


class EmbeddingProvider(Protocol):
    """Turns texts into vectors with one fixed model (DESIGN-001 §10)."""

    @property
    def model(self) -> str:
        """Identifier of the model that produces the vectors; stored with each vector."""
        ...

    def embed(self, texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        """Return one vector per text, in input order.

        Raises:
            ProviderError: a subclass describing why the call failed.
        """
        ...


class ProviderError(AppError):
    """A failed provider call. ``reason`` is for logs: status and error type, never content.

    Args:
        reason: Short technical cause, e.g. ``"HTTP 503"`` or ``"timeout"``.
        retryable: Whether the same request may succeed if sent again later.
        status: HTTP status, when there was a response.
        retry_after: Seconds the provider asked us to wait (``Retry-After``), if any.
    """

    CODE: ClassVar[ErrorCode]
    RETRYABLE: ClassVar[bool]

    def __init__(
        self,
        reason: str,
        *,
        retryable: bool | None = None,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Create the error with the subclass's code."""
        super().__init__(self.CODE, details={"status": status} if status else None)
        self.reason = reason
        self.retryable = self.RETRYABLE if retryable is None else retryable
        self.status = status
        self.retry_after = retry_after


class ProviderRateLimitedError(ProviderError):
    """HTTP 429: a free-tier quota was hit; waiting usually helps (Phase 3 finding)."""

    CODE = ErrorCode.PROVIDER_RATE_LIMITED
    RETRYABLE = True


class ProviderUnavailableError(ProviderError):
    """Server error, timeout, or network failure; a retired model (404) is not retryable."""

    CODE = ErrorCode.PROVIDER_UNAVAILABLE
    RETRYABLE = True


class ProviderAuthError(ProviderError):
    """The key is missing, invalid, or not allowed to use the model."""

    CODE = ErrorCode.PROVIDER_AUTH
    RETRYABLE = False


class ProviderBadResponseError(ProviderError):
    """The provider rejected the request (other 4xx) or answered with unusable data."""

    CODE = ErrorCode.PROVIDER_BAD_RESPONSE
    RETRYABLE = False
