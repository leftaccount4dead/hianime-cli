"""Terminal output: colours, tables, prompts. No dependencies on the rest."""

from __future__ import annotations

import os
import shutil
import sys
from typing import TYPE_CHECKING, Iterable, Sequence

from .site import Anime, Episode

if TYPE_CHECKING:
    from .site import Details

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"


def _colour_enabled() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()


COLOUR = _colour_enabled()


def paint(text: str, code: str) -> str:
    if not COLOUR:
        return text
    return f"{code}{text}{RESET}"


def bold(text: str) -> str:
    return paint(text, BOLD)


def dim(text: str) -> str:
    return paint(text, DIM)


def info(text: str) -> None:
    print(paint(text, CYAN))


def ok(text: str) -> None:
    print(paint(text, GREEN))


def warn(text: str) -> None:
    print(paint(text, YELLOW), file=sys.stderr)


def fail(text: str) -> None:
    print(paint(text, RED), file=sys.stderr)


def width() -> int:
    try:
        return max(60, shutil.get_terminal_size().columns)
    except OSError:
        return 80


def _clip(text: str, size: int) -> str:
    if len(text) <= size:
        return text
    if size <= 1:
        return text[:size]
    return text[: size - 1] + "…"


def print_anime(items: Sequence[Anime]) -> None:
    if not items:
        warn("nothing to show")
        return
    index_w = len(str(len(items)))
    title_w = max(20, min(52, width() - index_w - 34))
    head = f"{'#'.rjust(index_w)}  {'TITLE'.ljust(title_w)}  {'TYPE'.ljust(6)} {'YEAR'.ljust(6)} {'SCORE'.rjust(5)}  SUB/DUB"
    print(bold(head))
    print(dim("-" * min(width(), len(head) + 8)))
    for i, item in enumerate(items, 1):
        score = item.score or "-"
        counts = "/".join(x or "-" for x in (item.sub, item.dub))
        print(
            f"{str(i).rjust(index_w)}  "
            f"{_clip(item.title, title_w).ljust(title_w)}  "
            f"{_clip(item.kind, 6).ljust(6)} "
            f"{_clip(item.year, 6).ljust(6)} "
            f"{score.rjust(5)}  "
            f"{counts}"
        )
    print(dim(f"{len(items)} result(s)"))


def print_episodes(episodes: Sequence[Episode], columns: int = 6) -> None:
    if not episodes:
        warn("no episodes")
        return
    cell = 7
    cols = max(1, min(columns, width() // cell))
    for start in range(0, len(episodes), cols):
        row = episodes[start : start + cols]
        print("".join(f"{ep.number:<{cell}}" for ep in row))
        marks = "".join("d" if ep.has_dub else " " for ep in row)
        if "d" in marks:
            print(dim(marks))


def print_detail(detail: "Details") -> None:
    print(bold(detail.title))
    if detail.chips:
        print(dim(" | ".join(detail.chips)))
    if detail.facts:
        for key, value in detail.facts.items():
            print(f"  {bold(key + ':')} {value}")
    if detail.genres:
        print(f"  {bold('Genres:')} {', '.join(detail.genres)}")
    if detail.story:
        print()
        print(_wrap(detail.story, width()))
    print()
    print(bold(f"Episodes ({len(detail.episodes)})"))
    print_episodes(detail.episodes)


def _wrap(text: str, size: int) -> str:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > size:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return "\n".join(lines)


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        print()
        raise
    return value or default


def ask_choice(prompt: str, choices: Iterable[str], default: str = "") -> str:
    options = list(choices)
    while True:
        value = ask(f"{prompt} ({'/'.join(options)})", default)
        if value in options:
            return value
        warn(f"pick one of: {', '.join(options)}")


def ask_number(prompt: str, low: int, high: int, default: int | None = None) -> int:
    while True:
        raw = ask(prompt, str(default) if default is not None else "")
        if not raw and default is None:
            continue
        try:
            value = int(raw)
        except ValueError:
            warn("numbers only")
            continue
        if low <= value <= high:
            return value
        warn(f"between {low} and {high}")
