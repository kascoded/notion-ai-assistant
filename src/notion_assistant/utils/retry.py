"""
Retry utility for Notion API rate limit (429) handling.
Uses asyncio.sleep only — never blocks the event loop.
"""
import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRY_AFTER_RE = re.compile(
    r"retry.after[\":\s]+(\d+(?:\.\d+)?)", re.IGNORECASE
)


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate_limit" in msg or "rate limit" in msg


def _parse_retry_after(exc: Exception) -> float | None:
    m = _RETRY_AFTER_RE.search(str(exc))
    return float(m.group(1)) if m else None


async def with_notion_retry(
    coro_fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    jitter: float = 0.5,
) -> T:
    """
    Execute an async callable with retry on Notion 429 rate limit errors.

    Args:
        coro_fn:     Zero-arg async callable (lambda or functools.partial).
        max_retries: Maximum number of retry attempts (not counting initial try).
        base_delay:  Base delay in seconds for exponential backoff.
        max_delay:   Hard cap on delay in seconds.
        jitter:      Max random jitter added to delay (prevents thundering herd).

    Raises:
        The original exception if all retries are exhausted or if the error
        is not a 429.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await coro_fn()
        except Exception as exc:
            if not _is_rate_limit(exc):
                raise

            last_exc = exc

            if attempt >= max_retries:
                logger.warning("Notion rate limit: exhausted %d retries", max_retries)
                raise

            retry_after = _parse_retry_after(exc)
            if retry_after is not None:
                delay = min(retry_after, max_delay)
            else:
                delay = min(base_delay * (2**attempt), max_delay)

            delay += random.uniform(0, jitter)

            logger.warning(
                "Notion rate limit (429) on attempt %d/%d — waiting %.1fs",
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_exc  # unreachable, satisfies type checker
