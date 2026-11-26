"""Command line front end: one-shot subcommands plus an interactive shell."""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import Sequence

from . import __version__
from .config import BASE_URL, CHARTS, Settings
from .errors import HianimeError, NoResultError, PlayerError
from .http import Http
from . import player as player_mod
from . import site, streams, ui
from .store import HistoryEntry, Store, stamp

BANNER = r"""
 _   _ _             _
| | | (_)_ __   __ _| |___   _ _ __   ___
| | | | | '_ \ / _` | / __| | | '_ \ / _ \
| |_| | | | | | (_| | \__ \ |_| | | | |  __/
 \___/|_|_| |_|\__, |_|___/\___|_| |_|\___|
               |___/
"""


class Session:
    """Holds the client, preferences and caches for one run."""

    def __init__(self) -> None:
        self.http = Http()
        self.settings = Settings()
        self.store = Store()
        self._details: dict[str, site.Details] = {}
        self._episodes: list[site.Episode] = []
        self._details_url = ""

    # -- targets --------------------------------------------------------
    def resolve_target(self, target: str) -> str:
        """Accept a URL, a slug, an index into the last search, or free text."""
        target = target.strip()
        if not target:
            raise NoResultError("no title given")
        if target.startswith("http://") or target.startswith("https://"):
            if "/watch-" in target:
                return site.details_url_from_watch(target)
            return target
        if "/watch-" in target:
            if target.startswith("/"):
                target = BASE_URL + target
            if target.startswith("watch-"):
                target = BASE_URL + "/" + target
            return site.details_url_from_watch(target)
        if "/details/" in target:
            if target.startswith("http"):
                return target
            return BASE_URL + (target if target.startswith("/") else "/" + target)
        if target.isdigit():
            results = self.store.search
            index = int(target)
            if 1 <= index <= len(results):
                return str(results[index - 1]["url"])
            raise NoResultError(
                f"no search result #{index}; run a search first ({len(results)} stored)"
            )
        results = site.search(self.http, target)
        self._remember(results)
        ui.print_anime(results)
        if len(results) == 1:
            return results[0].url
        if not results:
            raise NoResultError(f"nothing matched {target!r}")
        raise NoResultError("pick a number from the list and run it again")

    def _remember(self, results: Sequence[site.Anime]) -> None:
        self.store.set_search(
            [
                {"url": r.url, "title": r.title, "kind": r.kind, "year": r.year}
                for r in results
            ]
        )

    def load(self, target: str) -> site.Details:
        url = self.resolve_target(target)
        if url in self._details:
            detail = self._details[url]
        else:
            detail = site.details(self.http, url)
            self._details[url] = detail
        self._details_url = detail.url
        self._episodes = list(detail.episodes)
        return detail

    @property
    def current(self) -> site.Details | None:
        if not self._details_url:
            return None
        return self._details.get(self._details_url)

    def episode(self, number: int) -> site.Episode:
        if not self._episodes:
            raise NoResultError("no title loaded; run info first")
        for ep in self._episodes:
            if ep.number == number:
                return ep
        available = f"{self._episodes[0].number}-{self._episodes[-1].number}"
        raise NoResultError(f"episode {number} not on this title (have {available})")

    # -- streaming ------------------------------------------------------
    def stream_for(
        self, number: int, lang: str | None = None, server: str | None = None
    ) -> tuple[streams.Stream, site.WatchConfig, site.Episode]:
        ep = self.episode(number)
        cfg = site.watch_config(self.http, ep.url)
        use_lang = lang or str(self.settings["lang"])
        use_server = server or str(self.settings["server"])
        stream = streams.probe(self.http, streams.resolve(self.http, cfg, use_lang, use_server))
        return stream, cfg, ep

    def note(self, cfg: site.WatchConfig, ep: site.Episode, lang: str) -> None:
        title = cfg.title or (self.current.title if self.current else "unknown")
        details_url = self._details_url or site.details_url_from_watch(ep.url)
        self.store.push(
            HistoryEntry(
                url=ep.url,
                details_url=details_url,
                title=title,
                episode=ep.number,
                lang=lang,
                server=str(self.settings["server"]),
                at=stamp(),
            )
        )


# ------------------------------------------------------------------ commands

def cmd_search(sess: Session, args: argparse.Namespace) -> int:
    results = site.search(sess.http, args.query, args.page)
    sess._remember(results)
    ui.print_anime(results)
    return 0


def cmd_charts(sess: Session, args: argparse.Namespace) -> int:
    results = site.chart(sess.http, args.kind, args.page)
    sess._remember(results)
    ui.print_anime(results)
    return 0


def cmd_genre(sess: Session, args: argparse.Namespace) -> int:
    results = site.genre(sess.http, args.slug, args.page)
    sess._remember(results)
    ui.print_anime(results)
    return 0


def cmd_az(sess: Session, args: argparse.Namespace) -> int:
    results = site.az_list(sess.http, args.letter, args.page)
    sess._remember(results)
    ui.print_anime(results)
    return 0


def cmd_schedule(sess: Session, args: argparse.Namespace) -> int:
    payload = site.schedule(sess.http, date=args.date, week=args.week)
    if args.week:
        days = payload.get("days", []) if isinstance(payload, dict) else []
        for day in days:
            date = day.get("date", "")
            items = day.get("items", [])
            ui.info(f"\n{date}")
            for item in items:
                print(f"  {item.get('time', ''):6} {item.get('title', '')} ep {item.get('episode', '')}")
        return 0
    items = payload  # type: ignore[assignment]
    if not items:
        ui.warn("nothing airing that day")
        return 0
    for item in items:
        print(f"{item.time:6}  {item.title}  ep {item.episode}")
        print(ui.dim(f"       {item.url}"))
    return 0


def cmd_random(sess: Session, args: argparse.Namespace) -> int:
    url = site.random_anime(sess.http)
    detail = site.details(sess.http, url)
    sess._details[detail.url] = detail
    sess._details_url = detail.url
    sess._episodes = list(detail.episodes)
    ui.print_detail(detail)
    return 0


def cmd_info(sess: Session, args: argparse.Namespace) -> int:
    detail = sess.load(args.target)
    ui.print_detail(detail)
    return 0


def _run_player(
    sess: Session,
    args: argparse.Namespace,
    number: int,
    *,
    download: bool,
) -> int:
    lang = args.lang or str(sess.settings["lang"])
    server = args.server or str(sess.settings["server"])
    stream, cfg, ep = sess.stream_for(number, lang, server)
    title = cfg.title or (sess.current.title if sess.current else "anime")
    label = f"{title} - episode {ep.number} ({lang}, {streams.SERVER_LABELS.get(server, server)})"
    ui.info(f"-> {label}")

    if download:
        name = f"{title} - {ep.number:03d} [{lang}]"
        path = player_mod.download(stream, name, quality=args.quality)
        ui.ok(f"saved {path}")
        sess.note(cfg, ep, lang)
        return 0

    start = args.start
    if not start and not getattr(args, "restart", False):
        start = int(player_mod.saved_position(ep.url))
    sess.note(cfg, ep, lang)
    skip_messages = []
    for name, enabled, spans in (
        (
            "intro",
            sess.settings["skip_intro"],
            stream.intro_spans or ((stream.intro,) if stream.intro else ()),
        ),
        (
            "outro",
            sess.settings["skip_outro"],
            stream.outro_spans or ((stream.outro,) if stream.outro else ()),
        ),
    ):
        if not enabled:
            continue
        if spans:
            skip_messages.append(f"{name}: " + ", ".join(
                f"{_format_timestamp(start)}–{_format_timestamp(end)}"
                for start, end in spans
            ))
        else:
            ui.warn(f"this stream has no {name} timing markers; automatic skip unavailable")
    if skip_messages:
        ui.info("auto-skip: " + " · ".join(skip_messages))
    player_mod.play(
        stream,
        label,
        start=start or 0,
        progress_key=ep.url,
        skip_intro=bool(sess.settings["skip_intro"]),
        skip_outro=bool(sess.settings["skip_outro"]),
        extra_args=args.player_args or None,
    )

    if args.no_next or not sess.settings["autoplay_next"]:
        return 0
    nxt = _next_episode(sess, ep.number)
    if nxt is None:
        return 0
    if not args.auto_next and sys.stdin.isatty():
        if ui.ask(f"play episode {nxt.number}?", "y").lower() not in ("y", "yes"):
            return 0
    return _run_player(sess, args, nxt.number, download=False)


def _format_timestamp(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _next_episode(sess: Session, number: int) -> site.Episode | None:
    skip_filler = bool(sess.settings["skip_filler"])
    return next(
        (
            ep
            for ep in sess._episodes
            if ep.number > number
            and not (skip_filler and ep.filler)
        ),
        None,
    )


def cmd_watch(sess: Session, args: argparse.Namespace) -> int:
    return _run_player(sess, args, args.episode, download=False)


def cmd_download(sess: Session, args: argparse.Namespace) -> int:
    return _run_player(sess, args, args.episode, download=True)


def cmd_continue(sess: Session, args: argparse.Namespace) -> int:
    last = sess.store.last
    if not last:
        ui.warn("nothing to continue")
        return 1
    detail = sess.load(str(last.get("details_url") or last["url"]))
    ui.info(f"resuming {detail.title} at episode {last.get('episode')}")
    number = int(last.get("episode") or 1)
    args.lang = last.get("lang")
    args.server = last.get("server")
    return _run_player(sess, args, number, download=False)


def cmd_history(sess: Session, args: argparse.Namespace) -> int:
    if args.clear:
        sess.store.clear()
        ui.ok("history cleared")
        return 0
    history = sess.store.history
    if not history:
        ui.warn("history is empty")
        return 0
    import datetime

    for row in history[: args.limit]:
        when = row.get("at")
        try:
            stamp_text = datetime.datetime.fromtimestamp(float(when)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError):
            stamp_text = "-"
        print(
            f"ep {str(row.get('episode', '?')).rjust(4)}  "
            f"{row.get('title', '')}  "
            f"{ui.dim(str(row.get('lang', '')))}  {ui.dim(stamp_text)}"
        )
        print(ui.dim(f"        {row.get('url', '')}"))
    return 0


def cmd_config(sess: Session, args: argparse.Namespace) -> int:
    if args.key is None:
        for key, value in sorted(sess.settings.data.items()):
            print(f"{key} = {value}")
        return 0
    if args.key not in sess.settings.data:
        ui.fail(f"unknown setting {args.key!r}")
        return 1
    if args.value is None:
        print(sess.settings.data[args.key])
        return 0
    raw: object = args.value
    current = sess.settings.data[args.key]
    try:
        if isinstance(current, bool):
            if args.value.lower() not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
                raise TypeError(f"{args.key} expects a boolean")
            raw = args.value.lower() in ("1", "true", "yes", "on")
        elif isinstance(current, int) and not isinstance(current, bool):
            raw = int(args.value)
        sess.settings[args.key] = raw
    except (KeyError, TypeError, ValueError) as exc:
        ui.fail(str(exc))
        return 1
    ui.ok(f"{args.key} = {raw}")
    return 0


def cmd_servers(sess: Session, args: argparse.Namespace) -> int:
    for name, label in streams.SERVER_LABELS.items():
        print(f"{ui.bold(name):12} {label}  {ui.dim('available')}")
    for name, reason in streams.UNSUPPORTED.items():
        print(f"{name:12} {ui.dim('unavailable - ' + reason)}")
    return 0


# ---------------------------------------------------------------- interactive

HELP = """
  s <query>          search
  c [kind] [page]    charts (top-airing, most-popular, most-favorite,
                     completed, top-upcoming, updates)
  g <genre> [page]   genre listing
  az [letter]        a-z list
  sched              today's airing schedule
  r                  random title
  i <n|url>          show details
  w <ep> [lang]      watch episode (lang: sub/dub)
  d <ep> [lang]      download episode
  n / p              next / previous episode
  lang sub|dub       default language
  srv backup|vidnest default server
  hist               history
  servers            list servers
  h                  this help
  q                  quit
"""


def interactive(sess: Session) -> int:
    if sys.stdin.isatty():
        print(ui.dim(BANNER))
        print(ui.dim(f"hianime-cli {__version__} - {BASE_URL}"))
        print(ui.dim(HELP))

    args = argparse.Namespace(
        lang=None, server=None, start=0, no_next=True, auto_next=False,
        player_args=None, quality="best",
    )
    last_target = ""
    while True:
        try:
            line = ui.ask("hianime")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            ui.fail(str(exc))
            continue
        if not parts:
            continue
        cmd, *rest = parts
        try:
            if cmd in ("q", "quit", "exit", "exit()"):
                return 0
            if cmd in ("h", "help", "?"):
                print(ui.dim(HELP))
            elif cmd == "s":
                if not rest:
                    ui.warn("s <query>")
                    continue
                results = site.search(sess.http, " ".join(rest))
                sess._remember(results)
                ui.print_anime(results)
                if results:
                    last_target = results[0].url
            elif cmd == "c":
                kind = rest[0] if rest else CHARTS[0]
                page = int(rest[1]) if len(rest) > 1 else 1
                results = site.chart(sess.http, kind, page)
                sess._remember(results)
                ui.print_anime(results)
                if results:
                    last_target = results[0].url
            elif cmd == "g":
                if not rest:
                    ui.warn("g <genre>")
                    continue
                results = site.genre(sess.http, rest[0])
                sess._remember(results)
                ui.print_anime(results)
                if results:
                    last_target = results[0].url
            elif cmd == "az":
                results = site.az_list(sess.http, rest[0] if rest else "")
                sess._remember(results)
                ui.print_anime(results)
                if results:
                    last_target = results[0].url
            elif cmd == "sched":
                cmd_schedule(sess, argparse.Namespace(date=None, week=False))
            elif cmd == "r":
                cmd_random(sess, argparse.Namespace())
            elif cmd in ("i", "info"):
                target = rest[0] if rest else last_target
                if not target:
                    ui.warn("i <n|url>")
                    continue
                detail = sess.load(target)
                last_target = detail.url
                ui.print_detail(detail)
            elif cmd in ("w", "watch", "d", "dl", "download"):
                if not rest:
                    ui.warn(f"{cmd} <episode> [sub|dub]")
                    continue
                if not sess.current:
                    ui.warn("load a title first: i <n|url>")
                    continue
                play_args = argparse.Namespace(
                    lang=rest[1] if len(rest) > 1 else None,
                    server=None,
                    start=0,
                    no_next=True,
                    auto_next=False,
                    player_args=None,
                    quality="best",
                )
                _run_player(
                    sess,
                    play_args,
                    int(rest[0]),
                    download=cmd in ("d", "dl", "download"),
                )
            elif cmd in ("n", "next"):
                if not sess.current or not sess._episodes:
                    ui.warn("nothing loaded")
                    continue
                current = sess.store.last
                cur = int(current.get("episode")) if current else 0
                nxt = _next_episode(sess, cur)
                if not nxt:
                    ui.warn("already at the last episode")
                    continue
                _run_player(sess, args, nxt.number, download=False)
            elif cmd in ("p", "prev"):
                if not sess.current or not sess._episodes:
                    ui.warn("nothing loaded")
                    continue
                current = sess.store.last
                cur = int(current.get("episode")) if current else 1
                prv = next(
                    (
                        ep for ep in reversed(sess._episodes)
                        if ep.number < cur
                        and not (sess.settings["skip_filler"] and ep.filler)
                    ),
                    None,
                )
                if not prv:
                    ui.warn("already at the first episode")
                    continue
                _run_player(sess, args, prv.number, download=False)
            elif cmd == "lang":
                if rest:
                    sess.settings["lang"] = rest[0]
                ui.info(f"lang = {sess.settings['lang']}")
            elif cmd == "srv":
                if rest:
                    sess.settings["server"] = rest[0]
                ui.info(f"server = {sess.settings['server']}")
            elif cmd == "hist":
                cmd_history(sess, argparse.Namespace(clear=False, limit=20))
            elif cmd == "servers":
                cmd_servers(sess, argparse.Namespace())
            else:
                ui.warn(f"unknown command {cmd!r} - h for help")
        except HianimeError as exc:
            ui.fail(str(exc))
        except (KeyError, TypeError) as exc:
            ui.fail(f"bad value: {exc}")
        except ValueError:
            ui.fail("expected a number there")
        except KeyboardInterrupt:
            print()
            ui.warn("interrupted")
    return 0


# --------------------------------------------------------------------- parser


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hianime",
        description="Terminal client for hianime.ms - search, browse, watch, download.",
        epilog="Run with no arguments for the interactive shell.",
    )
    parser.add_argument("--version", action="version", version=f"hianime-cli {__version__}")
    sub = parser.add_subparsers(dest="command")

    def target(p: argparse.ArgumentParser) -> None:
        p.add_argument("target", help="URL, slug, search index, or free text")

    def playback(p: argparse.ArgumentParser) -> None:
        p.add_argument("--lang", choices=("sub", "dub"), help="audio track")
        p.add_argument("--server", choices=streams.RESOLVERS, help="stream server")
        p.add_argument("--start", type=nonnegative_int, default=0, metavar="SECONDS")
        p.add_argument(
            "--restart",
            action="store_true",
            help="ignore the saved playback position and start at the beginning",
        )
        p.add_argument("--player-args", nargs=argparse.REMAINDER, metavar="ARG",
                       help="passed through to mpv after --")
        p.add_argument("--no-next", action="store_true", help="stop after this episode")
        p.add_argument("--auto-next", action="store_true",
                       help="never prompt before the next episode")

    p = sub.add_parser("search", help="search the library")
    p.add_argument("query")
    p.add_argument("--page", type=positive_int, default=1)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("charts", help="chart listings")
    p.add_argument("kind", nargs="?", default=CHARTS[0], choices=CHARTS)
    p.add_argument("--page", type=positive_int, default=1)
    p.set_defaults(func=cmd_charts)

    p = sub.add_parser("genre", help="list a genre")
    p.add_argument("slug")
    p.add_argument("--page", type=positive_int, default=1)
    p.set_defaults(func=cmd_genre)

    p = sub.add_parser("az", help="a-z listing")
    p.add_argument("letter", nargs="?", default="all")
    p.add_argument("--page", type=positive_int, default=1)
    p.set_defaults(func=cmd_az)

    p = sub.add_parser("schedule", help="airing schedule")
    p.add_argument("--date", help="YYYY-MM-DD, defaults to today")
    p.add_argument("--week", action="store_true")
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("random", help="a random title")
    p.set_defaults(func=cmd_random)

    p = sub.add_parser("info", help="show details and the episode table")
    target(p)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("watch", help="play an episode")
    p.add_argument("episode", type=positive_int)
    p.add_argument("--url", help="details or watch URL when no title is loaded")
    playback(p)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("download", help="save an episode with ffmpeg")
    p.add_argument("episode", type=positive_int)
    p.add_argument("--url", help="details or watch URL when no title is loaded")
    p.add_argument("--quality", choices=("best", "reencode"), default="best")
    playback(p)
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("continue", help="resume the last thing you watched")
    playback(p)
    p.set_defaults(func=cmd_continue)

    p = sub.add_parser("history", help="watch history")
    p.add_argument("--clear", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("servers", help="list stream servers")
    p.set_defaults(func=cmd_servers)

    p = sub.add_parser("config", help="read or write settings")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    return parser


def _preload_watch_target(sess: Session, args: argparse.Namespace) -> None:
    """`watch`/`download` accept --url so they work without an info step."""
    url = getattr(args, "url", None)
    if url:
        detail = sess.load(url)
        sess._details_url = detail.url


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.command:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .tui import run

            return run(Session())
        return interactive(Session())

    sess = Session()
    try:
        if args.command in ("watch", "download"):
            _preload_watch_target(sess, args)
            if not sess.current:
                raise NoResultError("give --url <details url>, or run info first")
        return args.func(sess, args)
    except HianimeError as exc:
        ui.fail(str(exc))
        return 1
    except KeyboardInterrupt:
        print()
        ui.warn("interrupted")
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
