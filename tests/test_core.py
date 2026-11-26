import unittest
from types import SimpleNamespace
from unittest.mock import patch

import curses
from hianimecli.cli import _format_timestamp, build_parser
from hianimecli.cli import _next_episode
from hianimecli import player
from hianimecli.player import safe_name, saved_position
from hianimecli.site import DETAILS_RE, Episode, _episodes, details_url_from_watch
from hianimecli.streams import Stream, _known_intro_spans, _timeline_spans
from hianimecli.tui import Browser


class FakeScreen:
    def __init__(self, keys):
        self.keys = iter(keys)

    def getmaxyx(self):
        return (24, 80)

    def addnstr(self, *args):
        pass

    def erase(self):
        pass

    def refresh(self):
        pass

    def getch(self):
        return next(self.keys)


class CoreTests(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(safe_name('A:B?/X'), "A_B__X")
        self.assertEqual(safe_name("." * 130), "untitled")

    def test_format_timestamp(self):
        self.assertEqual(_format_timestamp(111), "01:51")
        self.assertEqual(_format_timestamp(3671), "1:01:11")

    def test_watch_url_to_details_url(self):
        url = "https://hianime.ms/watch-one-piece-episode-12-1a877"
        self.assertEqual(
            details_url_from_watch(url),
            "https://hianime.ms/details/one-piece-1a877",
        )

    def test_details_regex(self):
        match = DETAILS_RE.search("/details/one-piece-1a877")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "one-piece-1a877")

    def test_positive_episode_and_page(self):
        parser = build_parser()
        args = parser.parse_args(["search", "naruto", "--page", "2"])
        self.assertEqual(args.page, 2)
        args = parser.parse_args(["watch", "12", "--url", "https://hianime.ms/watch-x-episode-12-a"])
        self.assertEqual(args.episode, 12)
        args = parser.parse_args(["watch", "12", "--restart"])
        self.assertTrue(args.restart)

    def test_arrow_keys_move_menu_selection(self):
        screen = FakeScreen([curses.KEY_DOWN, curses.KEY_ENTER])
        session = SimpleNamespace(settings={"lang": "sub", "server": "backup"})
        with patch("hianimecli.tui.curses.has_colors", return_value=False):
            browser = Browser(screen, session)
            self.assertEqual(browser._menu("Menu", ["first", "second"]), 1)

    def test_episode_parser_marks_filler_class(self):
        episodes = _episodes(
            '<a class="hk-ep hk-ep--filler" href="/watch-show-episode-1-a" '
            'data-ep="1" data-name="Filler"></a>'
            '<a class="hk-ep" href="/watch-show-episode-2-b" '
            'data-ep="2" data-name="Canon"></a>'
        )
        self.assertEqual([episode.filler for episode in episodes], [True, False])

    def test_timeline_parser_accepts_multiple_spans_and_rejects_bad_ranges(self):
        self.assertEqual(
            _timeline_spans(
                {"intro": [[31, 111], {"start": 140, "end": 165}, [200, 190]]},
                "intro",
            ),
            ((31, 111), (140, 165)),
        )

    def test_known_black_clover_intro_is_series_specific(self):
        self.assertEqual(
            _known_intro_spans("BLACK CLOVER", ((31, 111),)),
            ((0, 37), (31, 111)),
        )
        self.assertEqual(
            _known_intro_spans("ONE PIECE", ((31, 111),)),
            ((31, 111),),
        )
        self.assertEqual(
            _known_intro_spans("Other series", ((31, 111),)),
            ((31, 111),),
        )

    def test_saved_position_reads_only_positive_finite_values(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "position.txt"
            with patch("hianimecli.player.progress_path", return_value=path):
                path.write_text("123.5", encoding="ascii")
                self.assertEqual(saved_position("episode"), 123.5)
                path.write_text("nan", encoding="ascii")
                self.assertEqual(saved_position("episode"), 0.0)

    def test_player_passes_stable_progress_key_and_skip_markers(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "episode.txt"
            stream = Stream(
                url="https://cdn.example/temporary-signed-url",
                server="backup",
                lang="sub",
                intro=(80, 100),
                outro=(1300, 1320),
            )
            with (
                patch("hianimecli.player.which", return_value="/usr/bin/mpv"),
                patch("hianimecli.player.progress_path", return_value=checkpoint),
                patch("hianimecli.player.saved_position", return_value=0),
                patch("hianimecli.player.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run,
            ):
                player.play(
                    stream,
                    "Title",
                    progress_key="https://hianime.ms/watch-title-episode-1-a",
                    skip_intro=True,
                    skip_outro=True,
                )
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["HIANIME_PROGRESS_FILE"], str(checkpoint))
            self.assertEqual(env["HIANIME_INTROS"], "[[80, 100]]")
            self.assertEqual(env["HIANIME_SKIP_OUTRO"], "1")

    def test_next_episode_skips_filler_when_enabled(self):
        session = SimpleNamespace(
            settings={"skip_filler": True},
            _episodes=[
                Episode(1, "/1", "one"),
                Episode(2, "/2", "two", filler=True),
                Episode(3, "/3", "three"),
            ],
        )
        self.assertEqual(_next_episode(session, 1).number, 3)


if __name__ == "__main__":
    unittest.main()
