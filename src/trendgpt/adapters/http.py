"""Bounded HTTPS reads for explicitly allowlisted public source hosts."""
from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED_HOSTS = {"store.steampowered.com", "www.roblox.com", "www.youtube.com"}


class SourceFetchError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


class _AllowlistRedirectHandler(HTTPRedirectHandler):
    """Do not let an allowlisted page redirect the client to an arbitrary host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl):
            raise SourceFetchError("redirect_host_not_allowed", "redirect target is outside the HTTPS source allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get_public_text(url: str, *, timeout: int = 15, max_bytes: int = 5_000_000) -> str:
    if not _allowed_url(url):
        raise SourceFetchError("host_not_allowed", "only allowlisted HTTPS source hosts are permitted")
    if timeout <= 0 or max_bytes <= 0:
        raise SourceFetchError("invalid_limit", "timeout and max_bytes must be positive")
    request = Request(url, headers={"User-Agent": "TrendGPT/0.1 (bounded public discovery)"})
    opener = build_opener(_AllowlistRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise SourceFetchError("http_status", f"unexpected HTTP status {status}", retryable=status in {429, 500, 502, 503, 504})
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise SourceFetchError("response_too_large", f"response exceeded {max_bytes} bytes")
            charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
    except SourceFetchError:
        raise
    except HTTPError as exc:
        raise SourceFetchError("http_error", f"HTTP status {exc.code}", retryable=exc.code in {429, 500, 502, 503, 504}) from exc
    except URLError as exc:
        raise SourceFetchError("network_error", "source request failed", retryable=True) from exc
    except TimeoutError as exc:
        raise SourceFetchError("timeout", "source request timed out", retryable=True) from exc
