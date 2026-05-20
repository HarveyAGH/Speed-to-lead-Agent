from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from tools import http_client


class _FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self.body


def test_request_json_with_retries_retries_retryable_http_error(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(
                url=request.full_url,
                code=500,
                msg="temporary",
                hdrs={},
                fp=BytesIO(b"temporary failure"),
            )
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(http_client, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_client.time, "sleep", lambda delay: None)

    result = http_client.request_json_with_retries(
        Request("https://example.test", method="GET"),
        attempts=2,
    )

    assert result == {"ok": True}
    assert calls["count"] == 2


def test_request_json_with_retries_does_not_retry_bad_request(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise HTTPError(
            url=request.full_url,
            code=400,
            msg="bad request",
            hdrs={},
            fp=BytesIO(b"bad request"),
        )

    monkeypatch.setattr(http_client, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="HTTP API error 400"):
        http_client.request_json_with_retries(
            Request("https://example.test", method="GET"),
            attempts=3,
        )

    assert calls["count"] == 1
