"""Bounded HTTPS reads for explicitly allowlisted public source hosts."""
from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ALLOWED_HOSTS = {"store.steampowered.com", "www.roblox.com", "www.youtube.com"}


class SourceFetchError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def get_public_text(url: str, *, timeout: int = 15, max_bytes: int = 5_000_000) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise SourceFetchError("host_not_allowed", "only allowlisted HTTPS source hosts are permitted")
    request = Request(url, headers={"User-Agent": "TrendGPT/0.1 (bounded public discovery)"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise SourceFetchError("http_status", f"unexpected HTTP status {status}", retryable=status in {429, 500, 502, 503, 504})
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise SourceFetchError("response_too_large", f"response exceeded {max_bytes} bytes")
            charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
    except HTTPError as exc:
        raise SourceFetchError("http_error", f"HTTP status {exc.code}", retryable=exc.code in {429, 500, 502, 503, 504}) from exc
    except URLError as exc:
        raise SourceFetchError("network_error", "source request failed", retryable=True) from exc
    except TimeoutError as exc:
        raise SourceFetchError("timeout", "source request timed out", retryable=True) from exc
