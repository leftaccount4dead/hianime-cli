"""One HTTP client for the whole app: shared cookie jar, browser headers, timeouts."""

from __future__ import annotations

import gzip
import http.cookiejar
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Mapping

from .config import USER_AGENT
from .errors import NetworkError

TIMEOUT = 25
MAX_BODY = 16 * 1024 * 1024  # a listing page is < 600 KB; refuse anything absurd
MAX_REDIRECTS = 8


@dataclass(frozen=True)
class Response:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes

    @property
    def text(self) -> str:
        charset = "utf-8"
        raw = self.headers.get("content-type", "")
        if "charset=" in raw:
            charset = raw.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


def _decompress(body: bytes, encoding: str) -> bytes:
    encoding = encoding.lower().strip()
    try:
        if encoding == "gzip":
            return gzip.decompress(body)
        if encoding == "deflate":
            return zlib.decompress(body)
    except (OSError, zlib.error):
        return body
    return body


class Http:
    """Cookie-keeping client. Redirects are followed except when asked not to."""

    def __init__(self, user_agent: str = USER_AGENT, timeout: int = TIMEOUT) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        redirector = urllib.request.HTTPRedirectHandler()
        redirector.max_redirections = MAX_REDIRECTS
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            redirector,
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        data: bytes | None = None,
        referer: str | None = None,
    ) -> Response:
        base = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            base["Referer"] = referer
        if headers:
            base.update(headers)

        req = urllib.request.Request(url, data=data, headers=base, method=method)

        try:
            with self._opener.open(req, timeout=self.timeout) as raw:
                body = raw.read(MAX_BODY + 1)
                if len(body) > MAX_BODY:
                    raise NetworkError(f"response too large: {url}")
                return Response(
                    status=raw.status,
                    url=raw.geturl(),
                    headers={k.lower(): v for k, v in raw.headers.items()},
                    body=_decompress(body, raw.headers.get("Content-Encoding", "")),
                )
        except urllib.error.HTTPError as exc:
            # 3xx without a handler, 4xx, 5xx - the body still carries the reason.
            body = exc.read(MAX_BODY)
            return Response(
                status=exc.code,
                url=exc.url or url,
                headers={k.lower(): v for k, v in exc.headers.items()},
                body=_decompress(body, exc.headers.get("Content-Encoding", "")),
            )
        except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as exc:
            raise NetworkError(f"{url}: {exc}") from exc

    def get(self, url: str, **kwargs: object) -> Response:
        return self.request(url, method="GET", **kwargs)  # type: ignore[arg-type]

    def post(
        self, url: str, data: bytes | None = None, **kwargs: object
    ) -> Response:
        return self.request(url, method="POST", data=data, **kwargs)  # type: ignore[arg-type]

    def redirect_target(self, url: str, **kwargs: object) -> str:
        """Follow a single redirect and report where it landed, without the body."""
        resp = self.get(url, **kwargs)  # type: ignore[arg-type]
        return resp.url


def build_url(base: str, path: str, query: Mapping[str, object] | None = None) -> str:
    url = urllib.parse.urljoin(base, path)
    if query:
        pairs = [(k, str(v)) for k, v in query.items() if v not in (None, "")]
        if pairs:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(pairs)
    return url
