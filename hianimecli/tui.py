"""Arrow-key terminal browser for interactive use."""

from __future__ import annotations

import curses
import textwrap
from argparse import Namespace
from typing import TYPE_CHECKING, Callable, Sequence

from . import site, streams, ui
from .config import CHARTS
from .errors import HianimeError
from .player import saved_position

if TYPE_CHECKING:
    from .cli import Session


class Browser:
    def __init__(self, screen: curses.window, session: Session) -> None:
        self.screen = screen
        self.session = session
        self.lang = str(session.settings["lang"])
        self.server = str(session.settings["server"])
        self._init_colors()
        self.status = "Up/down to move · Enter to select · q to go back"

    def _init_colors(self) -> None:
        self.colors = False
        try:
            if not curses.has_colors() or curses.COLORS < 8:
                return
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_GREEN)
            curses.init_pair(3, curses.COLOR_MAGENTA, -1)
            curses.init_pair(4, curses.COLOR_CYAN, -1)
            curses.init_pair(5, curses.COLOR_YELLOW, -1)
            self.colors = True
        except curses.error:
            self.colors = False

    def _color(self, pair: int, fallback: int = curses.A_NORMAL) -> int:
        return curses.color_pair(pair) if self.colors else fallback

    def run(self) -> None:
        self.screen.keypad(True)
        curses.curs_set(0)
        while True:
            selected = self._menu(
                "hianime-cli",
                [
                    "Search",
                    "Top airing",
                    "Most popular",
                    "Most favorite",
                    "Completed",
                    "Top upcoming",
                    "Recently updated",
                    "Browse A-Z",
                    "Browse genre",
                    "Airing schedule",
                    "Random title",
                    "Continue watching",
                    "Watch history",
                    "Settings",
                    "Quit",
                ],
            )
            if selected is None or selected == 14:
                return
            try:
                if selected == 0:
                    query = self._prompt("Search title")
                    if query:
                        self._results("Search: " + query, lambda page: site.search(
                            self.session.http, query, page
                        ))
                elif selected in range(1, 7):
                    kind = CHARTS[selected - 1]
                    self._results(kind.replace("-", " ").title(), lambda page: site.chart(
                        self.session.http, kind, page
                    ))
                elif selected == 7:
                    letter = self._menu("Browse A-Z", ["All", *list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")])
                    if letter is not None:
                        value = "" if letter == 0 else chr(ord("a") + letter - 1)
                        self._results("A-Z", lambda page: site.az_list(
                            self.session.http, value, page
                        ))
                elif selected == 8:
                    genre = self._prompt("Genre slug")
                    if genre:
                        self._results("Genre: " + genre, lambda page: site.genre(
                            self.session.http, genre, page
                        ))
                elif selected == 9:
                    items = site.schedule(self.session.http)
                    labels = [f"{item.time}  {item.title}  ·  ep {item.episode}" for item in items]
                    self._pick_anime(labels, [item.url for item in items])
                elif selected == 10:
                    detail = site.details(self.session.http, site.random_anime(self.session.http))
                    self._detail(detail)
                elif selected == 11:
                    last = self.session.store.last
                    if not last:
                        self.status = "Nothing in watch history yet."
                    else:
                        detail = self.session.load(str(last.get("details_url") or last["url"]))
                        number = int(last.get("episode") or 1)
                        self._detail(detail, number)
                elif selected == 12:
                    self._history()
                elif selected == 13:
                    self._settings()
            except (HianimeError, ValueError, KeyError, TypeError) as exc:
                self.status = str(exc)
                self._message("Could not complete that action", self.status)

    def _draw(self, title: str, rows: Sequence[str], selected: int, offset: int) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self.screen.addnstr(
            0, 0, " HIANIME // NEON TERMINAL ", max(1, width - 1),
            curses.A_BOLD | self._color(3),
        )
        self.screen.addnstr(
            1, 0, f"  {title.upper()}  " + "─" * max(1, width - len(title) - 7),
            max(1, width - 1), self._color(1),
        )
        visible = max(1, height - 5)
        offset = max(0, min(offset, max(0, len(rows) - visible)))
        for line, item in enumerate(rows[offset : offset + visible], 2):
            index = offset + line - 2
            attr = (
                curses.A_BOLD | self._color(2, curses.A_REVERSE)
                if index == selected
                else curses.A_NORMAL
            )
            self.screen.addnstr(line, 0, item, max(1, width - 1), attr)
        footer = self.status
        if len(rows) > visible:
            footer += f"  ·  {selected + 1}/{len(rows)}"
        self.screen.addnstr(
            height - 3, 0, "─" * max(1, width - 1), max(1, width - 1), self._color(1)
        )
        self.screen.addnstr(
            height - 2, 0, f" ◆ {footer}", max(1, width - 1),
            curses.A_DIM | self._color(4),
        )
        self.screen.refresh()

    def _menu(self, title: str, rows: Sequence[str], start: int = 0) -> int | None:
        if not rows:
            self._message(title, "Nothing to show.")
            return None
        selected = min(max(start, 0), len(rows) - 1)
        offset = 0
        while True:
            height = self.screen.getmaxyx()[0]
            visible = max(1, height - 5)
            if selected < offset:
                offset = selected
            elif selected >= offset + visible:
                offset = selected - visible + 1
            self._draw(title, rows, selected, offset)
            key = self.screen.getch()
            if key in (curses.KEY_UP, ord("k")):
                selected = (selected - 1) % len(rows)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = (selected + 1) % len(rows)
            elif key == curses.KEY_PPAGE:
                selected = max(0, selected - visible)
            elif key == curses.KEY_NPAGE:
                selected = min(len(rows) - 1, selected + visible)
            elif key in (curses.KEY_ENTER, 10, 13):
                return selected
            elif key in (27, ord("q")):
                return None

    def _prompt(self, label: str) -> str:
        _, width = self.screen.getmaxyx()
        self.screen.erase()
        self.screen.addnstr(0, 0, label, max(1, width - 1), curses.A_BOLD)
        self.screen.addnstr(2, 0, "> ", max(1, width - 1))
        self.screen.refresh()
        curses.echo()
        curses.curs_set(1)
        try:
            value = self.screen.getstr(2, 2, max(1, width - 4)).decode("utf-8", "replace")
        finally:
            curses.noecho()
            curses.curs_set(0)
        return value.strip()

    def _message(self, title: str, message: str) -> None:
        height, width = self.screen.getmaxyx()
        self.screen.erase()
        self.screen.addnstr(0, 0, title, max(1, width - 1), curses.A_BOLD)
        lines = textwrap.wrap(message, max(1, width - 2)) or [""]
        for index, line in enumerate(lines[: max(1, height - 3)], 2):
            self.screen.addnstr(index, 0, line, max(1, width - 1))
        self.screen.addnstr(height - 2, 0, "Press any key to continue", max(1, width - 1), curses.A_DIM)
        self.screen.refresh()
        self.screen.getch()

    def _results(
        self, title: str, fetch: Callable[[int], list[site.Anime]], page: int = 1
    ) -> None:
        while True:
            results = fetch(page)
            self.session._remember(results)
            labels = [
                f"{item.title}  ·  {item.kind or 'Anime'} {item.year}  ·  sub {item.sub or '-'} / dub {item.dub or '-'}"
                for item in results
            ]
            selected = self._menu(f"{title}  ·  page {page}", [*labels, "Next page"])
            if selected is None:
                return
            if selected == len(results):
                page += 1
                continue
            self._detail(self.session.load(results[selected].url))

    def _pick_anime(self, labels: Sequence[str], urls: Sequence[str]) -> None:
        selected = self._menu("Airing today", labels)
        if selected is not None:
            self._detail(self.session.load(urls[selected]))

    def _detail(self, detail: site.Details, start_episode: int = 0) -> None:
        try:
            start_index = next(
                index for index, ep in enumerate(detail.episodes) if ep.number == start_episode
            ) if start_episode else 0
        except StopIteration:
            start_index = 0
        if start_episode:
            episode_url = detail.episodes[start_index].url
            position = int(saved_position(episode_url))
            if position:
                minutes, seconds = divmod(position, 60)
                hours, minutes = divmod(minutes, 60)
                timestamp = (
                    f"{hours}:{minutes:02d}:{seconds:02d}"
                    if hours else f"{minutes:02d}:{seconds:02d}"
                )
                self.status = f"Continue episode {start_episode} from {timestamp}."
        selected = start_index
        offset = 0
        while True:
            height, width = self.screen.getmaxyx()
            visible = max(1, height - 8)
            if selected < offset:
                offset = selected
            elif selected >= offset + visible:
                offset = selected - visible + 1

            self.screen.erase()
            self.screen.addnstr(0, 0, detail.title, max(1, width - 1), curses.A_BOLD)
            self.screen.addnstr(
                1, 0,
                f"Language: {self.lang.upper()}   Server: {streams.SERVER_LABELS.get(self.server, self.server)}",
                max(1, width - 1),
            )
            metadata = " · ".join(detail.chips + detail.genres)
            if metadata:
                self.screen.addnstr(2, 0, metadata, max(1, width - 1), curses.A_DIM)
            for line, ep in enumerate(detail.episodes[offset : offset + visible], 4):
                index = offset + line - 4
                dub_label = "dub" if ep.has_dub else "sub only"
                filler_label = "  [FILLER]" if ep.filler else ""
                label = f"Episode {ep.number}  {ep.name}  [{dub_label}]{filler_label}".rstrip()
                self.screen.addnstr(
                    line, 0, label, max(1, width - 1),
                    (curses.A_BOLD | self._color(2, curses.A_REVERSE))
                    if index == selected
                    else (self._color(5) if ep.filler else curses.A_NORMAL),
                )
            controls = "↑/↓ select · Enter play · d download · l sub/dub · v server · q back"
            self.screen.addnstr(height - 3, 0, controls, max(1, width - 1), curses.A_DIM)
            self.screen.addnstr(
                height - 2, 0, self.status, max(1, width - 1), curses.A_DIM
            )
            self.screen.refresh()
            key = self.screen.getch()
            if key in (curses.KEY_UP, ord("k")):
                selected = (selected - 1) % len(detail.episodes)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = (selected + 1) % len(detail.episodes)
            elif key == curses.KEY_PPAGE:
                selected = max(0, selected - visible)
            elif key == curses.KEY_NPAGE:
                selected = min(len(detail.episodes) - 1, selected + visible)
            elif key == ord("l"):
                self.lang = "dub" if self.lang == "sub" else "sub"
                self.session.settings["lang"] = self.lang
            elif key == ord("v"):
                servers = list(streams.RESOLVERS)
                self.server = servers[(servers.index(self.server) + 1) % len(servers)]
                self.session.settings["server"] = self.server
            elif key in (curses.KEY_ENTER, 10, 13, ord("d")):
                episode = detail.episodes[selected]
                download = key == ord("d")
                if self.lang == "dub" and not episode.has_dub:
                    self.status = f"Episode {episode.number} has no dub track."
                    continue
                restart = False
                position = int(saved_position(episode.url))
                if position and not download:
                    minutes, seconds = divmod(position, 60)
                    hours, minutes = divmod(minutes, 60)
                    timestamp = (
                        f"{hours}:{minutes:02d}:{seconds:02d}"
                        if hours else f"{minutes:02d}:{seconds:02d}"
                    )
                    choice = self._menu(
                        f"Saved progress · episode {episode.number}",
                        [f"Resume from {timestamp}", "Start from beginning", "Cancel"],
                    )
                    if choice is None or choice == 2:
                        continue
                    restart = choice == 1
                self._play(episode.number, download, restart=restart)
            elif key in (27, ord("q")):
                return

    def _play(self, number: int, download: bool, *, restart: bool = False) -> None:
        from .cli import _run_player

        args = Namespace(
            lang=self.lang,
            server=self.server,
            start=0,
            restart=restart,
            no_next=False,
            auto_next=False,
            player_args=None,
            quality="best",
        )
        try:
            curses.endwin()
            _run_player(self.session, args, number, download=download)
            self.status = f"Finished episode {number}."
        except HianimeError as exc:
            self.status = str(exc)
        finally:
            curses.reset_prog_mode()
            self.screen.keypad(True)
            self.screen.clear()
            self.screen.refresh()

    def _history(self) -> None:
        rows = self.session.store.history
        if not rows:
            self.status = "Watch history is empty."
            return
        labels = []
        for row in rows:
            labels.append(
                f"{row.get('title', 'Unknown')}  ·  ep {row.get('episode', '?')}  ·  "
                f"{str(row.get('lang', '')).upper()}"
            )
        selected = self._menu("Watch history", labels)
        if selected is None:
            return
        entry = rows[selected]
        detail = self.session.load(str(entry.get("details_url") or entry["url"]))
        self._detail(detail, int(entry.get("episode") or 1))

    def _settings(self) -> None:
        while True:
            rows = [
                f"Language: {self.lang.upper()}",
                f"Server: {streams.SERVER_LABELS.get(self.server, self.server)}",
                f"Autoplay next: {'on' if self.session.settings['autoplay_next'] else 'off'}",
                f"Skip intros: {'on' if self.session.settings['skip_intro'] else 'off'}",
                f"Skip outros: {'on' if self.session.settings['skip_outro'] else 'off'}",
                f"Skip filler on next/previous: {'on' if self.session.settings['skip_filler'] else 'off'}",
                "Back",
            ]
            choice = self._menu("Settings", rows)
            if choice is None or choice == 6:
                return
            if choice == 0:
                self.lang = "dub" if self.lang == "sub" else "sub"
                self.session.settings["lang"] = self.lang
            elif choice == 1:
                servers = list(streams.RESOLVERS)
                self.server = servers[(servers.index(self.server) + 1) % len(servers)]
                self.session.settings["server"] = self.server
            elif choice == 2:
                self.session.settings["autoplay_next"] = not self.session.settings["autoplay_next"]
            elif choice == 3:
                self.session.settings["skip_intro"] = not self.session.settings["skip_intro"]
            elif choice == 4:
                self.session.settings["skip_outro"] = not self.session.settings["skip_outro"]
            elif choice == 5:
                self.session.settings["skip_filler"] = not self.session.settings["skip_filler"]


def run(session: Session) -> int:
    """Run the full-screen browser when attached to a terminal."""
    try:
        curses.wrapper(lambda screen: Browser(screen, session).run())
        return 0
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        ui.fail(f"terminal UI failed: {exc}")
        return 1
