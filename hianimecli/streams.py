"""Turn a watch configuration into a playable stream URL.

Two servers are wired up, both verified against the live site:

  backup   hianime /stream/<token>/<lang>  -> megaplay.buzz -> getSources (AES-CBC)
  vidnest  new.vidnest.fun/hianime/...     -> cipher envelope (AES-GCM)

The remaining site servers are gated behind a request signature or a dead
origin, so they are reported as unavailable rather than faked.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass, field

from .config import BASE_URL
from .errors import ResolveError
from .http import Http
from .site import WatchConfig

# --- megaplay ------------------------------------------------------------
MEGAPLAY_CDN_REFERER = "https://megaplay.buzz/"
SRC_KEY = b"i?LMTAx0Q6,:}50U"
SRC_IV = b"W0;27ToaUpl_P%'c"
CDN_TOKEN_SECRET = b"MpCdnT0k3n!9f2K#xQ7vL5mR8wN1pY4s"
CDN_PATH_RE = re.compile(r"/([a-f0-9]{32})/([a-f0-9]{32})/", re.I)

# --- vidnest -------------------------------------------------------------
VIDNEST_API = "https://new.vidnest.fun/hianime/anime/{al}/{ep}/{lang}/hd-2"
VIDNEST_SECRET = "K3p8vQ2mX9rL5wZ0fN7bG1sH4tJ6dC9_y8S3wM1nQ5pL2"
VIDNEST_REFERER = "https://vidnest.fun/"

SERVER_LABELS = {"backup": "Ryu", "vidnest": "Volt"}
UNSUPPORTED = {
    "tryembed": "Warp signs its bootstrap request; no public signature path",
    "vidnest-pahe": "Ayame origin returns 502 upstream",
}
RESOLVERS = ("backup", "vidnest")
KNOWN_INTRO_SPANS: dict[str, tuple[tuple[int, int], ...]] = {
    "black clover": ((0, 37),),
}


@dataclass(frozen=True)
class Subtitle:
    label: str
    url: str


@dataclass(frozen=True)
class Stream:
    url: str
    server: str
    lang: str
    headers: dict[str, str] = field(default_factory=dict)
    subtitles: tuple[Subtitle, ...] = ()
    intro: tuple[int, int] | None = None
    outro: tuple[int, int] | None = None
    intro_spans: tuple[tuple[int, int], ...] = ()
    outro_spans: tuple[tuple[int, int], ...] = ()
    kind: str = "hls"

    @property
    def referer(self) -> str:
        return self.headers.get("Referer", "")


def _b64url_decode(raw: str) -> bytes:
    padded = raw.replace("-", "+").replace("_", "/")
    padded += "=" * ((4 - len(padded) % 4) % 4)
    return base64.b64decode(padded)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    # WebCrypto zero-pads short keys; the site's key string is 16 bytes for a
    # 32-byte AES key, so pad before import exactly as the page does.
    key = key.ljust(32, b"\0")[:32]
    iv = iv.ljust(16, b"\0")[:16]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    try:
        return unpadder.update(plain) + unpadder.finalize()
    except ValueError as exc:
        raise ResolveError("stream payload failed padding check") from exc


def _attach_cdn_token(url: str) -> str:
    """HMAC-signed token the shared CDN requires for playback."""
    match = CDN_PATH_RE.search(url)
    if not match or "token=" in url:
        return url
    key = f"{match.group(1).lower()}/{match.group(2).lower()}"
    message = f"{int(time.time()) + 90}|{key}".encode()
    signature = hmac.new(CDN_TOKEN_SECRET, message, hashlib.sha256).digest()
    token = _b64url_encode(message) + "." + _b64url_encode(signature)
    return url + ("&" if "?" in url else "?") + "token=" + token


def _with_audio_type(url: str, lang: str) -> str:
    if not re.search(r"/master\.m3u8(?:\?|$)", url, re.I) or "t=" in url:
        return url
    return url + ("&" if "?" in url else "?") + "t=" + lang


def _timeline_span(span: object) -> tuple[int, int] | None:
    if isinstance(span, dict):
        try:
            return int(span["start"]), int(span["end"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(span, (list, tuple)) and len(span) == 2:
        if any(isinstance(value, (dict, list, tuple)) for value in span):
            return None
        try:
            return int(span[0]), int(span[1])
        except (TypeError, ValueError):
            return None
    return None


def _timeline_spans(payload: dict, key: str) -> tuple[tuple[int, int], ...]:
    value = payload.get(key)
    if isinstance(value, dict):
        candidates = [value]
    elif isinstance(value, (list, tuple)):
        if len(value) == 2 and not any(
            isinstance(item, (dict, list, tuple)) for item in value
        ):
            candidates = [value]
        else:
            candidates = list(value)
    else:
        return ()
    return tuple(
        span
        for item in candidates
        if (span := _timeline_span(item)) is not None
        and span[0] >= 0
        and span[1] > span[0]
    )


def _timeline(payload: dict, key: str) -> tuple[int, int] | None:
    spans = _timeline_spans(payload, key)
    return spans[0] if spans else None


def _subtitles(payload: dict) -> tuple[Subtitle, ...]:
    out: list[Subtitle] = []
    for row in payload.get("tracks") or payload.get("subtitles") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or row.get("type") or "").lower()
        if kind in ("thumbnails", "sprite", "chapters", "preview"):
            continue
        url = row.get("file") or row.get("url")
        if not url:
            continue
        out.append(Subtitle(label=str(row.get("label") or "Subtitle"), url=str(url)))
    return tuple(out)


def _known_intro_spans(
    title: str, spans: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, int], ...]:
    known = KNOWN_INTRO_SPANS.get(title.strip().casefold(), ())
    return tuple(sorted(set((*known, *spans))))


# ------------------------------------------------------------------ Ryu

def _resolve_megaplay(http: Http, cfg: WatchConfig, lang: str) -> Stream:
    # /stream/<token>/<lang> 302s straight to the megaplay player page, so the
    # body that comes back already is the page we need to parse.
    landing = http.get(f"{BASE_URL}/stream/{cfg.token}/{lang}", referer=cfg.url)
    html_text = landing.text
    if not html_text.strip():
        raise ResolveError("megaplay player page came back empty")

    id_match = re.search(r'data-id="(\d+)"', html_text)
    if not id_match:
        raise ResolveError("megaplay page did not expose a source id")
    type_match = re.search(r"type\s*:\s*'([a-z]+)'", html_text)
    media_type = type_match.group(1) if type_match else lang

    resp = http.get(
        _sources_endpoint(landing.url, id_match.group(1)),
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
        },
        referer=landing.url,
    )
    if resp.status != 200:
        raise ResolveError(f"getSources returned {resp.status}")
    try:
        payload = json.loads(resp.text)
    except ValueError as exc:
        raise ResolveError("getSources returned non-JSON") from exc
    if payload.get("error") or payload.get("message"):
        raise ResolveError(str(payload.get("message") or payload.get("error")))

    if payload.get("enc"):
        try:
            decoded = _aes_cbc_decrypt(
                _b64url_decode(str(payload["enc"])), SRC_KEY, SRC_IV
            )
            source = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ResolveError("could not decrypt the source payload") from exc
    elif isinstance(payload.get("sources"), dict):
        source = payload["sources"]
    else:
        raise ResolveError("getSources response carried no source")

    url = source.get("file") or source.get("url")
    if not isinstance(url, str) or not url:
        raise ResolveError("source payload has no file url")

    intro_spans = _timeline_spans(payload, "intro") or _timeline_spans(source, "intro")
    outro_spans = _timeline_spans(payload, "outro") or _timeline_spans(source, "outro")
    intro_spans = _known_intro_spans(cfg.title, intro_spans)
    return Stream(
        url=_attach_cdn_token(_with_audio_type(url, media_type)),
        server="backup",
        lang=lang,
        headers={"Referer": MEGAPLAY_CDN_REFERER},
        subtitles=_subtitles(payload),
        intro=intro_spans[0] if intro_spans else None,
        outro=outro_spans[0] if outro_spans else None,
        intro_spans=intro_spans,
        outro_spans=outro_spans,
    )


def _sources_endpoint(landing: str, source_id: str) -> str:
    origin = "/".join(landing.split("/")[:3])
    return f"{origin}/stream/getSources?id={source_id}&platform=OTHER&st=other&_={int(time.time()*1000)}"


# ---------------------------------------------------------------- Volt

def _resolve_vidnest(http: Http, cfg: WatchConfig, lang: str) -> Stream:
    if not cfg.al:
        raise ResolveError("watch config has no id for the vidnest mirror")
    nonce = _b64url_encode(secrets.token_bytes(16))
    api = VIDNEST_API.format(al=cfg.al, ep=cfg.episode, lang=lang)
    resp = http.get(
        f"{api}?_n={nonce}",
        headers={"Accept": "application/json", "Origin": VIDNEST_REFERER},
        referer=VIDNEST_REFERER,
    )
    if resp.status != 200:
        raise ResolveError(f"vidnest returned {resp.status}")
    try:
        payload = json.loads(resp.text)
    except ValueError as exc:
        raise ResolveError("vidnest returned non-JSON") from exc

    if payload.get("v") == 2 and payload.get("d"):
        payload = _decrypt_vidnest(payload)

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ResolveError(str(payload.get("error") or "vidnest returned no sources"))
    chosen = next(
        (s for s in sources if isinstance(s, dict) and s.get("type") == "hls"),
        sources[0],
    )
    url = chosen.get("file") or chosen.get("url") or chosen.get("src")
    if not isinstance(url, str) or not url:
        raise ResolveError("vidnest source has no url")

    intro_spans = _timeline_spans(payload, "intro")
    outro_spans = _timeline_spans(payload, "outro")
    intro_spans = _known_intro_spans(cfg.title, intro_spans)
    return Stream(
        url=_with_audio_type(url, lang),
        server="vidnest",
        lang=lang,
        headers={"Referer": MEGAPLAY_CDN_REFERER},
        subtitles=_subtitles(payload),
        intro=intro_spans[0] if intro_spans else None,
        outro=outro_spans[0] if outro_spans else None,
        intro_spans=intro_spans,
        outro_spans=outro_spans,
    )


def _decrypt_vidnest(payload: dict) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = payload.get("n")
    cipher = payload.get("d")
    if not isinstance(nonce, str) or not isinstance(cipher, str):
        raise ResolveError("vidnest cipher envelope is malformed")
    key = hashlib.sha256(f"{nonce}|{VIDNEST_SECRET}".encode()).digest()
    raw = _b64url_decode(cipher)
    if len(raw) <= 12:
        raise ResolveError("vidnest cipher is too short")
    try:
        plain = AESGCM(key).decrypt(raw[:12], raw[12:], None)
        decoded = json.loads(plain.decode("utf-8"))
    except Exception as exc:  # InvalidTag, JSON, unicode
        raise ResolveError("vidnest payload failed authentication") from exc
    if not isinstance(decoded, dict):
        raise ResolveError("vidnest payload is not an object")
    return decoded


# ------------------------------------------------------------------ entry

def resolve(http: Http, cfg: WatchConfig, lang: str, server: str) -> Stream:
    if lang not in ("sub", "dub"):
        raise ResolveError(f"unknown language {lang!r}")
    if server in UNSUPPORTED:
        raise ResolveError(f"{server} is unavailable: {UNSUPPORTED[server]}")
    if server == "vidnest":
        return _resolve_vidnest(http, cfg, lang)
    if server != "backup":
        raise ResolveError(f"unknown server {server!r}; use {', '.join(RESOLVERS)}")
    return _resolve_megaplay(http, cfg, lang)


PROBE_PREFIX = 1024
PROBE_REFERERS = (
    MEGAPLAY_CDN_REFERER,
    "https://vidnest.fun/",
    "https://new.vidnest.fun/",
)


def probe(http: Http, stream: Stream) -> Stream:
    """Confirm the URL actually serves media, trying the referers the CDNs accept.

    Returns the stream with the working header set, or raises.
    """
    candidates: list[dict[str, str]] = [dict(stream.headers)]
    for referer in PROBE_REFERERS:
        if referer not in {c.get("Referer") for c in candidates}:
            candidates.append({"Referer": referer})

    last_status = 0
    for headers in candidates:
        request_headers: dict[str, str] = {"Range": f"bytes=0-{PROBE_PREFIX}"}
        request_headers.update(headers)
        resp = http.get(stream.url, headers=request_headers, referer=headers.get("Referer"))
        last_status = resp.status
        if resp.status in (200, 206) and _looks_like_playlist(resp.body):
            return Stream(
                url=stream.url,
                server=stream.server,
                lang=stream.lang,
                headers=headers,
                subtitles=stream.subtitles,
                intro=stream.intro,
                outro=stream.outro,
                intro_spans=stream.intro_spans,
                outro_spans=stream.outro_spans,
                kind=stream.kind,
            )
    raise ResolveError(f"stream rejected playback (HTTP {last_status})")


def _looks_like_playlist(body: bytes) -> bool:
    head = body.lstrip()[:16]
    return head.startswith(b"#EXTM3U") or head.startswith(b"{")
