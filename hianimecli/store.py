"""Local state: watch history, the last search, the resume point."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import state_dir

HISTORY_LIMIT = 200
SEARCH_LIMIT = 60


@dataclass
class HistoryEntry:
    url: str
    details_url: str
    title: str
    episode: int
    lang: str
    server: str
    at: float


class Store:
    """One JSON file under the state dir. Writes are atomic."""

    def __init__(self) -> None:
        self.path: Path = state_dir() / "state.json"
        self.data: dict[str, Any] = {
            "history": [],
            "search": [],
            "last": None,
        }
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            history = raw.get("history")
            if isinstance(history, list):
                self.data["history"] = [h for h in history if isinstance(h, dict)]
            search = raw.get("search")
            if isinstance(search, list):
                self.data["search"] = [r for r in search if isinstance(r, dict)]
            last = raw.get("last")
            if isinstance(last, dict):
                self.data["last"] = last

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    # -- search ---------------------------------------------------------
    def set_search(self, results: list[dict[str, Any]]) -> None:
        self.data["search"] = results[:SEARCH_LIMIT]
        self.save()

    @property
    def search(self) -> list[dict[str, Any]]:
        results = self.data.get("search")
        return results if isinstance(results, list) else []

    # -- history --------------------------------------------------------
    def push(self, entry: HistoryEntry) -> None:
        history = [h for h in self.data.get("history", []) if isinstance(h, dict)]
        history = [h for h in history if h.get("url") != entry.url]
        history.insert(0, asdict(entry))
        self.data["history"] = history[:HISTORY_LIMIT]
        self.data["last"] = asdict(entry)
        self.save()

    @property
    def history(self) -> list[dict[str, Any]]:
        value = self.data.get("history")
        return value if isinstance(value, list) else []

    @property
    def last(self) -> dict[str, Any] | None:
        value = self.data.get("last")
        return value if isinstance(value, dict) else None

    def clear(self) -> None:
        self.data = {"history": [], "search": [], "last": None}
        self.save()


def stamp() -> float:
    return time.time()
