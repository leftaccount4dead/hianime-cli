import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hianimecli.config import Settings
from hianimecli.store import HistoryEntry, Store


class ConfigTests(unittest.TestCase):
    def test_rejects_invalid_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("hianimecli.config.config_dir", return_value=Path(tmp)):
                settings = Settings()
                with self.assertRaises(TypeError):
                    settings["lang"] = "raw"

    def test_accepts_valid_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("hianimecli.config.config_dir", return_value=Path(tmp)):
                settings = Settings()
                settings["lang"] = "dub"
                settings["server"] = "vidnest"
                settings["skip_intro"] = False
                settings["skip_filler"] = True
                reloaded = Settings()
                self.assertEqual(settings["lang"], "dub")
                self.assertEqual(settings["server"], "vidnest")
                self.assertFalse(reloaded["skip_intro"])
                self.assertTrue(reloaded["skip_filler"])


class StoreTests(unittest.TestCase):
    def test_history_is_bounded_and_last_is_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("hianimecli.store.state_dir", return_value=Path(tmp)):
                store = Store()
                for number in range(205):
                    store.push(HistoryEntry(
                        url=f"https://example/ep-{number}",
                        details_url="https://example/title",
                        title="Title",
                        episode=number,
                        lang="sub",
                        server="backup",
                        at=float(number),
                    ))
                self.assertEqual(len(store.history), 200)
                self.assertEqual(store.last["episode"], 204)


if __name__ == "__main__":
    unittest.main()
