"""Filesystem locations and defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "hianime-cli"

BASE_URL = "https://hianime.ms"

# The site is one origin behind Cloudflare; every request needs a browser
# user agent or the tiles come back empty.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULTS: dict[str, Any] = {
    "lang": "sub",        # sub | dub
    "server": "backup",   # backup (Ryu) | vidnest (Volt)
    "player": "mpv",
    "autoplay_next": True,
    "skip_intro": True,
    "skip_outro": True,
    "skip_filler": False,
}

CHARTS = (
    "top-airing",
    "most-popular",
    "most-favorite",
    "completed",
    "top-upcoming",
    "updates",
)

LANGS = ("sub", "dub")
SERVERS = ("backup", "vidnest")


def _xdg(env: str, fallback: Path) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser() if value else fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME


def download_dir() -> Path:
    return Path.home() / "Videos" / "hianime"


class Settings:
    """User preferences. Unknown keys are rejected at the boundary."""

    def __init__(self) -> None:
        self.path = config_dir() / "settings.json"
        self.data: dict[str, Any] = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key not in DEFAULTS or not isinstance(value, type(DEFAULTS[key])):
                    continue
                try:
                    self._validate(key, value)
                except (KeyError, TypeError):
                    continue
                self.data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._validate(key, value)
        self.data[key] = value
        self.save()

    @staticmethod
    def _validate(key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting {key!r}")
        if not isinstance(value, type(DEFAULTS[key])):
            raise TypeError(f"{key} expects {type(DEFAULTS[key]).__name__}")
        if key == "lang" and value not in LANGS:
            raise TypeError(f"lang must be one of: {', '.join(LANGS)}")
        if key == "server" and value not in SERVERS:
            raise TypeError(f"server must be one of: {', '.join(SERVERS)}")
        if key == "player" and not value.strip():
            raise TypeError("player cannot be empty")
