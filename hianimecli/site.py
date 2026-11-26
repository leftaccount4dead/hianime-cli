"""Scraping layer for hianime.ms: listings, details, episode tables, watch config."""

from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin

from .config import BASE_URL, CHARTS
from .errors import NetworkError, NoResultError, ParseError
from .http import Http, build_url

MAX_LISTING_PAGE = 500   # az-list runs to 336; refuse a runaway page number
MAX_EPISODES = 5000      # One Piece sits at 1180; anything past this is corrupt HTML
DETAILS_RE = re.compile(r"/details/([a-z0-9-]+)")
WATCH_RE = re.compile(r"/watch-([a-z0-9-]+-episode-(\d+)-[a-z0-9]+)")


# ---------------------------------------------------------------- helpers

def _strip(markup: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markup)
    return re.sub(r"\s+", " ", htmllib.unescape(text)).strip()


def _attr(block: str, name: str) -> str | None:
    match = re.search(rf'\b{name}="([^"]*)"', block)
    if match:
        return htmllib.unescape(match.group(1))
    match = re.search(rf"\b{name}='([^']*)'", block)
    return htmllib.unescape(match.group(1)) if match else None


def _span_text(block: str, cls: str) -> str | None:
    match = re.search(rf'<span class="[^"]*{re.escape(cls)}[^"]*"[^>]*>(.*?)</span>', block, re.S)
    return _strip(match.group(1)) if match else None


def _require(match: re.Match[str] | None, what: str) -> re.Match[str]:
    if not match:
        raise ParseError(f"could not find {what} on the page")
    return match


# ---------------------------------------------------------------- models

@dataclass(frozen=True)
class Anime:
    slug: str
    url: str
    title: str
    kind: str = ""
    year: str = ""
    score: str = ""
    sub: str = ""
    dub: str = ""
    poster: str = ""


@dataclass(frozen=True)
class Episode:
    number: int
    url: str
    name: str
    has_dub: bool = False
    filler: bool = False


@dataclass(frozen=True)
class Details:
    url: str
    slug: str
    title: str
    story: str
    facts: dict[str, str]
    genres: list[str]
    chips: list[str]
    sub_count: str
    dub_count: str
    episodes: list[Episode]
    start_url: str
    newest_url: str


@dataclass(frozen=True)
class WatchConfig:
    url: str
    token: str
    episode: int
    lang: str
    al: str
    mirror: dict[str, str] = field(default_factory=dict)
    servers: list[tuple[str, str]] = field(default_factory=list)
    title: str = ""
    episode_title: str = ""
    total: int = 0

    @property
    def slug(self) -> str:
        match = WATCH_RE.search(self.url)
        return match.group(1) if match else ""

    def mirror_url(self, server: str, lang: str) -> str | None:
        template = self.mirror.get(server)
        if not template:
            return None
        return template.format(al=self.al, ep=self.episode, lang=lang)


@dataclass(frozen=True)
class ScheduleItem:
    time: str
    title: str
    episode: str
    url: str


# ---------------------------------------------------------------- listings

def _parse_tiles(page: str) -> list[Anime]:
    found: list[Anime] = []
    for chunk in page.split('<article class="hk-tile"')[1:]:
        block = chunk.split("</article>")[0]
        href = re.search(r'href="(?:https://hianime\.ms)?(/details/[^"]+)"', block)
        if not href:
            continue
        url = urljoin(BASE_URL, href.group(1))
        slug = DETAILS_RE.search(url)
        title = _attr(block, "data-en") or ""
        if not title:
            name = re.search(r'class="hk-tile__name".*?<a[^>]*>(.*?)</a>', block, re.S)
            title = _strip(name.group(1)) if name else ""
        meta = re.search(r'class="hk-tile__meta"[^>]*>(.*?)</p>', block, re.S)
        cells = re.findall(r"<span>([^<]*)</span>", meta.group(1)) if meta else []
        found.append(
            Anime(
                slug=slug.group(1) if slug else "",
                url=url,
                title=title,
                kind=cells[0] if len(cells) > 0 else "",
                year=cells[1] if len(cells) > 1 else "",
                score=_span_text(block, "hk-tile__score") or "",
                sub=_span_text(block, "hk-tag--sub") or "",
                dub=_span_text(block, "hk-tag--dub") or "",
                poster=_attr(block, "src") or "",
            )
        )
    return found


def _listing(http: Http, path: str, query: dict[str, object] | None = None) -> list[Anime]:
    resp = http.get(build_url(BASE_URL, path, query))
    if resp.status != 200:
        raise NetworkError(f"listing returned HTTP {resp.status}: {path}")
    tiles = _parse_tiles(resp.text)
    if not tiles:
        raise NoResultError(f"nothing came back from {path}")
    return tiles


def _valid_page(page: int) -> int:
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= MAX_LISTING_PAGE:
        raise NoResultError(f"page must be between 1 and {MAX_LISTING_PAGE}")
    return page


def search(http: Http, query: str, page: int = 1) -> list[Anime]:
    page = _valid_page(page)
    if not query.strip():
        raise NoResultError("empty search")
    params: dict[str, object] = {"q": query.strip()}
    if page > 1:
        params["page"] = page
    return _listing(http, "/search", params)


def chart(http: Http, kind: str, page: int = 1) -> list[Anime]:
    page = _valid_page(page)
    if kind not in CHARTS:
        raise NoResultError(f"unknown chart {kind!r}; try {', '.join(CHARTS)}")
    return _listing(http, f"/{kind}", {"page": page} if page > 1 else None)


def genre(http: Http, slug: str, page: int = 1) -> list[Anime]:
    page = _valid_page(page)
    slug = slug.strip().lower()
    if not slug:
        raise NoResultError("empty genre")
    return _listing(http, f"/genre/{slug}", {"page": page} if page > 1 else None)


def az_list(http: Http, letter: str = "", page: int = 1) -> list[Anime]:
    page = _valid_page(page)
    path = "/az-list"
    query: dict[str, object] = {"page": page} if page > 1 else None
    if letter and letter.lower() != "all":
        return _listing(http, f"/az-list/{letter.lower()}", query)
    return _listing(http, path, query)


def random_anime(http: Http) -> str:
    """Follow /random to wherever it lands and return a details URL."""
    resp = http.get(build_url(BASE_URL, "/random"))
    if resp.status != 200:
        raise NetworkError(f"random returned HTTP {resp.status}")
    match = DETAILS_RE.search(resp.url)
    if match:
        return resp.url
    match = DETAILS_RE.search(resp.text)
    if not match:
        raise ParseError("random did not resolve to a title")
    return urljoin(BASE_URL, match.group(0))


def schedule(http: Http, date: str | None = None, week: bool = False) -> object:
    """Return a list of ScheduleItem for a date, or the raw week payload."""
    query: dict[str, object] = {"week": 1} if week else {"date": date or _today()}
    resp = http.get(
        build_url(BASE_URL, "/api/schedule", query),
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    if resp.status != 200:
        raise ParseError(f"schedule endpoint returned {resp.status}")
    try:
        payload = json.loads(resp.text)
    except ValueError as exc:
        raise ParseError("schedule endpoint returned non-JSON") from exc
    if week:
        return payload
    if not isinstance(payload, list):
        raise ParseError("unexpected schedule shape")
    items = []
    for row in payload[:MAX_LISTING_PAGE]:
        if not isinstance(row, dict):
            continue
        items.append(
            ScheduleItem(
                time=str(row.get("time", "")),
                title=str(row.get("title") or row.get("english_title") or ""),
                episode=str(row.get("episode", "")),
                url=str(row.get("url", "")),
            )
        )
    return items


def _today() -> str:
    import datetime

    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- details

def details(http: Http, url: str) -> Details:
    resp = http.get(url)
    if resp.status != 200:
        raise NetworkError(f"details returned HTTP {resp.status}: {url}")
    page = resp.text
    final_url = resp.url

    title_m = _require(re.search(r'<h1[^>]*class="hk-title__h[^"]*"[^>]*>(.*?)</h1>', page, re.S), "the title")
    title = _strip(title_m.group(1))

    slug_m = DETAILS_RE.search(final_url)
    slug = slug_m.group(1) if slug_m else ""

    story_m = re.search(
        r'class="hk-clamp[^"]*"[^>]*itemprop="description"[^>]*>(.*?)</div>', page, re.S
    )
    story = _strip(story_m.group(1)) if story_m else ""

    facts: dict[str, str] = {}
    for dt, dd in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", page, re.S):
        facts[_strip(dt)] = _strip(dd)

    genres: list[str] = []
    genre_block = re.search(r'<div class="hk-chips hk-facts__genres">(.*?)</div>', page, re.S)
    if genre_block:
        genres = [
            _strip(m)
            for m in re.findall(r'<a class="hk-chip"[^>]*>(.*?)</a>', genre_block.group(1), re.S)
        ]

    chips = [
        _strip(m)
        for m in re.findall(r'<div class="hk-title__chips">(.*?)</div>', page, re.S)
    ]
    chip_cells: list[str] = []
    if chips:
        chip_cells = [_strip(x) for x in re.findall(r"<span[^>]*>(.*?)</span>", chips[0], re.S)]
        chip_cells = [c for c in chip_cells if c]

    sub_count = next((c.replace("Sub", "").strip() for c in chip_cells if c.lower().startswith("sub")), "")
    dub_count = next((c.replace("Dub", "").strip() for c in chip_cells if c.lower().startswith("dub")), "")

    episodes = _episodes(page)
    if not episodes:
        raise ParseError("no episodes found on the details page")

    start = re.search(r'<a class="hk-btn" href="([^"]*watch-[^"]*)"', page)
    newest = re.search(r'<a class="hk-btn hk-btn--soft" href="([^"]*watch-[^"]*)"', page)

    return Details(
        url=final_url,
        slug=slug,
        title=title,
        story=story,
        facts=facts,
        genres=genres,
        chips=chip_cells,
        sub_count=sub_count,
        dub_count=dub_count,
        episodes=episodes,
        start_url=urljoin(BASE_URL, start.group(1)) if start else (episodes[0].url if episodes else ""),
        newest_url=urljoin(BASE_URL, newest.group(1)) if newest else (episodes[-1].url if episodes else ""),
    )


def _episodes(page: str) -> list[Episode]:
    out: list[Episode] = []
    # `hk-ep` appears bare and as `hk-ep hk-ep--filler`, so match the class
    # token rather than the literal string.
    for match in re.finditer(r'<a class="hk-ep\b[^"]*"[^>]*>.*?</a>', page, re.S):
        if len(out) >= MAX_EPISODES:
            break
        block = match.group(0)
        href = _attr(block, "href")
        number = _attr(block, "data-ep")
        if not href or not number:
            continue
        try:
            n = int(number)
        except ValueError:
            continue
        out.append(
            Episode(
                number=n,
                url=urljoin(BASE_URL, href),
                name=_attr(block, "data-name") or "",
                has_dub="hk-ep__dub" in block,
                filler=bool(
                    re.search(
                        r"(?:^|\s)hk-ep--filler(?:\s|$)",
                        _attr(block, "class") or "",
                    )
                ),
            )
        )
    out.sort(key=lambda e: e.number)
    return out


# ---------------------------------------------------------------- watch

def watch_config(http: Http, url: str) -> WatchConfig:
    resp = http.get(url)
    if resp.status != 200:
        raise NetworkError(f"watch page returned HTTP {resp.status}: {url}")
    page = resp.text
    final_url = resp.url

    raw = _attr(page, "data-hk-watch")
    if not raw:
        raise ParseError("watch page has no player configuration")
    try:
        cfg = json.loads(raw)
    except ValueError as exc:
        raise ParseError("player configuration is not valid JSON") from exc

    token = cfg.get("token")
    if not token:
        raise ParseError("player configuration has no stream token")

    title_m = re.search(r'<h1 class="hk-watch__h".*?data-en="([^"]*)"', page, re.S)
    ep_title = re.search(r'data-hk-now-title>([^<]*)<', page)
    total_m = re.search(r'data-total="(\d+)"', page)

    servers_raw = _attr(page, "data-servers")
    servers: list[tuple[str, str]] = []
    if servers_raw:
        try:
            parsed = json.loads(servers_raw)
            servers = [(str(a), str(b)) for a, b in parsed if isinstance(a, str) and isinstance(b, str)]
        except (ValueError, TypeError):
            servers = []

    return WatchConfig(
        url=final_url,
        token=str(token),
        episode=int(cfg.get("ep") or _episode_from_url(final_url)),
        lang=str(cfg.get("lang") or "sub"),
        al=str(cfg.get("al") or ""),
        mirror={str(k): str(v) for k, v in (cfg.get("mirror") or {}).items()},
        servers=servers,
        title=htmllib.unescape(title_m.group(1)) if title_m else "",
        episode_title=_strip(ep_title.group(1)) if ep_title else "",
        total=int(total_m.group(1)) if total_m else 0,
    )


def _episode_from_url(url: str) -> int:
    match = WATCH_RE.search(url)
    return int(match.group(2)) if match else 0


def episode_url(episodes: Iterable[Episode], number: int) -> str:
    for ep in episodes:
        if ep.number == number:
            return ep.url
    raise NoResultError(f"episode {number} does not exist on this title")


def details_url_from_watch(watch_url: str) -> str:
    """`/watch-one-piece-episode-12-1a877` -> `/details/one-piece-1a877`."""
    match = re.match(
        r"^(https?://[^/]+)/(?:watch-)(.+)-episode-\d+-([a-z0-9]+)/?(?:\?.*)?$",
        watch_url,
    )
    if not match:
        raise ParseError(f"not a watch url: {watch_url}")
    return f"{match.group(1)}/details/{match.group(2)}-{match.group(3)}"
