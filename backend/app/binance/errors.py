"""Binance error taxonomy.

Binance reports failures both as HTTP status codes and as a negative ``code``
in the JSON body.  The distinction that matters to the trading engine is not
the specific code but the *class* of failure: whether retrying is safe, whether
the client must back off, and whether the local clock is at fault.
"""

from __future__ import annotations

from app.core.errors import AppError

# Documented Binance error codes this system reacts to specifically.  Anything
# not listed is handled by its class, never by a guessed meaning (§114).
CODE_INVALID_TIMESTAMP = -1021  # request outside recvWindow
CODE_INVALID_SIGNATURE = -1022
CODE_TOO_MANY_REQUESTS = -1003
CODE_UNKNOWN_SYMBOL = -1121


class BinanceError(AppError):
    """Base for every Binance failure."""

    code = "BINANCE_ERROR"
    status_code = 502

    def __init__(
        self,
        message: str,
        *,
        binance_code: int | None = None,
        http_status: int | None = None,
        **kwargs: object,
    ) -> None:
        metadata = {
            key: value
            for key, value in (
                ("binance_code", binance_code),
                ("http_status", http_status),
            )
            if value is not None
        }
        super().__init__(message, metadata=metadata or None, **kwargs)  # type: ignore[arg-type]
        self.binance_code = binance_code
        self.http_status = http_status

    @property
    def retryable(self) -> bool:
        """Whether re-sending the identical request is safe and worthwhile."""
        return False


class BinanceTransportError(BinanceError):
    """Network-level failure: no response, or an unreadable one.

    Safe to retry for idempotent reads.  Order placement must never be retried
    blindly on this — the request may have been executed (§9).
    """

    code = "BINANCE_UNAVAILABLE"
    status_code = 503

    @property
    def retryable(self) -> bool:
        return True


class BinanceRateLimitError(BinanceError):
    """HTTP 429 / 418, or error code -1003.

    Retryable only after honouring the server's ``Retry-After``.  Ignoring this
    escalates to an IP ban (§71).
    """

    code = "BINANCE_RATE_LIMITED"
    status_code = 429

    def __init__(
        self, message: str, *, retry_after_seconds: float | None = None, **kwargs: object
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.retry_after_seconds = retry_after_seconds

    @property
    def retryable(self) -> bool:
        return True


class BinanceServerError(BinanceError):
    """HTTP 5xx from Binance.

    The exchange's own documentation warns that a 5xx is an *unknown* execution
    status, not a confirmed failure.  Reads may be retried; writes may not.
    """

    code = "BINANCE_SERVER_ERROR"
    status_code = 502

    @property
    def retryable(self) -> bool:
        return True


class BinanceRequestError(BinanceError):
    """HTTP 4xx other than 429 — a malformed or rejected request.

    Never retryable: the same request will be rejected identically.
    """

    code = "BINANCE_REQUEST_REJECTED"
    status_code = 400


class BinanceTimestampError(BinanceRequestError):
    """Error -1021: the request fell outside ``recvWindow``.

    Signals local clock drift.  The caller must re-synchronise against server
    time rather than widening ``recvWindow`` to paper over it (§72).
    """

    code = "BINANCE_TIMESTAMP_INVALID"

    @property
    def retryable(self) -> bool:
        """Retryable once the clock has been re-synced.

        Unlike other 4xx rejections this is not deterministic: -1021 means the
        exchange refused the request *before* acting on it, so re-sending with
        a corrected timestamp is safe even for an order -- nothing was
        executed.  The retry budget still bounds it.
        """
        return True


class BinanceAuthError(BinanceRequestError):
    """Rejected credentials or signature.  Never retried, never logged with the key."""

    code = "BINANCE_AUTH_FAILED"
    status_code = 401
