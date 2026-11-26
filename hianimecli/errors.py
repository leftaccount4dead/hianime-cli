"""Error types. Every failure path raises one of these; nothing else escapes."""

from __future__ import annotations


class HianimeError(Exception):
    """Base for everything the CLI knows how to explain."""


class NetworkError(HianimeError):
    """The request never produced a usable response."""


class ParseError(HianimeError):
    """The page came back but the markup we depend on is gone."""


class ResolveError(HianimeError):
    """A server could not be turned into a playable stream."""


class NoResultError(HianimeError):
    """Search or listing came back empty."""


class PlayerError(HianimeError):
    """mpv or ffmpeg is missing or exited badly."""
