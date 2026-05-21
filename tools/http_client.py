from __future__ import annotations

import json
import random
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def request_json_with_retries(
    request: Request,
    *,
    timeout: int = 20,
    attempts: int = 3,
    base_delay: float = 0.5,
) -> dict[str, Any]:
    """Execute a JSON HTTP request with small retry/backoff behavior.

    This is intentionally thin: callers still own provider-specific error
    handling, but transient network/provider failures get a second chance.
    """
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in RETRYABLE_STATUS_CODES or attempt == attempts:
                raise RuntimeError(f"HTTP API error {exc.code}: {body}") from exc

            last_error = RuntimeError(f"HTTP API error {exc.code}: {body}")
            _sleep_before_retry(exc, attempt, base_delay)
        except (TimeoutError, URLError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"HTTP API request failed: {exc}") from exc

            last_error = exc
            _sleep_before_retry(None, attempt, base_delay)

    raise RuntimeError(f"HTTP API request failed after retries: {last_error}")


def _sleep_before_retry(
    exc: HTTPError | None,
    attempt: int,
    base_delay: float,
) -> None:
    retry_after = None
    if exc is not None:
        retry_after = exc.headers.get("Retry-After")

    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            delay = base_delay * (2 ** (attempt - 1))
    else:
        delay = base_delay * (2 ** (attempt - 1))

    jitter = random.uniform(0, base_delay)
    time.sleep(min(delay + jitter, 5.0))
