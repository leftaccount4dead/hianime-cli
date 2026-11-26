"""Playback and downloads. mpv plays, ffmpeg saves; both are shell-outs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import USER_AGENT, download_dir, state_dir
from .errors import PlayerError
from .streams import Stream

BLOCKED = r'[<>:"/\\|?*\x00-\x1f]'


def safe_name(text: str, limit: int = 120) -> str:
    cleaned = re.sub(BLOCKED, "_", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:limit] or "untitled"


def which(binary: str) -> str:
    found = shutil.which(binary)
    if not found:
        raise PlayerError(f"{binary} is not installed or not on PATH")
    return found


def _header_args(stream: Stream) -> list[str]:
    args: list[str] = []
    if stream.referer:
        args.append(f"--referrer={stream.referer}")
    args.append(f"--user-agent={USER_AGENT}")
    return args


def progress_path(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return state_dir() / "progress" / f"{key}.txt"


def saved_position(url: str) -> float:
    try:
        position = float(progress_path(url).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return 0.0
    return position if math.isfinite(position) and position > 0 else 0.0


def play(
    stream: Stream,
    title: str,
    *,
    start: int = 0,
    progress_key: str | None = None,
    skip_intro: bool = False,
    skip_outro: bool = False,
    extra_args: list[str] | None = None,
) -> None:
    binary = which("mpv")
    script = Path(__file__).with_name("mpv_hianime.lua")
    cmd = [binary]
    cmd += _header_args(stream)
    cmd += [f"--title={title}"]
    cmd += [f"--script={script}"]
    resume_key = progress_key or stream.url
    position = start
    if position > 0:
        cmd += [f"--start={position}"]
    for index, sub in enumerate(stream.subtitles, 1):
        # Thumbnails are not subtitles; only language tracks get passed in.
        if "thumb" in sub.url or "preview" in sub.url:
            continue
        cmd += [f"--sub-file={sub.url}"]
        if index > 8:
            break
    if extra_args:
        cmd += extra_args
    cmd.append(stream.url)

    env = os.environ.copy()
    progress_file = progress_path(resume_key)
    try:
        progress_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PlayerError(f"could not create progress directory: {exc}") from exc
    env["HIANIME_PROGRESS_FILE"] = str(progress_file)
    intro_spans = stream.intro_spans or ((stream.intro,) if stream.intro else ())
    outro_spans = stream.outro_spans or ((stream.outro,) if stream.outro else ())
    env["HIANIME_INTROS"] = json.dumps(intro_spans)
    env["HIANIME_OUTROS"] = json.dumps(outro_spans)
    env["HIANIME_SKIP_INTRO"] = "1" if skip_intro else "0"
    env["HIANIME_SKIP_OUTRO"] = "1" if skip_outro else "0"
    try:
        result = subprocess.run(cmd, check=False, env=env)
    except OSError as exc:
        raise PlayerError(f"could not launch mpv: {exc}") from exc
    if result.returncode not in (0, 2):
        # mpv exits 2 when it could not open the source; 0 on a clean quit.
        raise PlayerError(f"mpv exited with code {result.returncode}")


def download(
    stream: Stream,
    filename: str,
    *,
    directory: Path | None = None,
    quality: str = "best",
) -> Path:
    binary = which("ffmpeg")
    target_dir = directory or download_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_name(filename)
    if (target_dir / f"{stem}.mp4").exists() or (target_dir / f"{stem}.mkv").exists():
        raise PlayerError(f"refusing to overwrite {stem}.mp4/.mkv")

    header_block = ""
    if stream.referer:
        header_block += f"Referer: {stream.referer}\r\n"
    header_block += f"User-Agent: {USER_AGENT}\r\n"

    # mp4 needs the AAC bitstream filter; if the audio is not ADTS that filter
    # rejects the mux, so fall back to matroska which takes AAC as-is.
    attempts = [
        (".mp4", ["-c", "copy", "-bsf:a", "aac_adtstoasc"]),
        (".mkv", ["-c", "copy"]),
    ]
    if quality != "best":
        attempts = [
            (
                ".mp4",
                ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac"],
            )
        ]

    last_code = 0
    for suffix, codec_args in attempts:
        target = target_dir / f"{stem}{suffix}"
        cmd = [binary, "-hide_banner", "-loglevel", "error", "-y"]
        cmd += ["-headers", header_block, "-i", stream.url]
        cmd += codec_args + [str(target)]
        try:
            result = subprocess.run(cmd, check=False)
        except OSError as exc:
            raise PlayerError(f"could not launch ffmpeg: {exc}") from exc
        last_code = result.returncode
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return target
        target.unlink(missing_ok=True)
    raise PlayerError(f"ffmpeg failed with code {last_code}")


def probe_player() -> str | None:
    """Return the configured player if it exists, else None."""
    try:
        which("mpv")
    except PlayerError:
        return None
    return "mpv"
