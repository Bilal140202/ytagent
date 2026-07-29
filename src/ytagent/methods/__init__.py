"""Method registry — maps method names to their implementing functions.

Each method module exports:
  - NAME: str                — the canonical method name (matches DEFAULT_METHODS)
  - download(video_id, out_dir, opts) -> MethodResult

The Orchestrator imports METHOD_REGISTRY and looks up methods by name from
the Truth Agent's ranked list.
"""

from __future__ import annotations

from typing import Any, Callable

from .base import MethodResult
from . import (
    cobalt,
    innertube_direct,
    invidious,
    piped,
    transcript_probe,
    ytdlp_audio_only,
    ytdlp_default,
    ytdlp_ios,
    ytdlp_jsless,
    ytdlp_single_file,
)

# Type alias for the method callable signature.
MethodFn = Callable[[str, Any, dict[str, Any] | None], MethodResult]


def _wrap(mod) -> MethodFn:
    """Wrap a method module's download function to inject its NAME into the result."""
    fn = mod.download
    name = mod.NAME

    def wrapped(video_id: str, out_dir, opts=None) -> MethodResult:
        result = fn(video_id, out_dir, opts)
        result.method = name
        return result

    wrapped.__name__ = f"{name}_wrapped"
    return wrapped


METHOD_REGISTRY: dict[str, MethodFn] = {
    transcript_probe.NAME:    _wrap(transcript_probe),
    ytdlp_default.NAME:       _wrap(ytdlp_default),
    ytdlp_jsless.NAME:        _wrap(ytdlp_jsless),
    ytdlp_ios.NAME:           _wrap(ytdlp_ios),
    ytdlp_single_file.NAME:   _wrap(ytdlp_single_file),
    ytdlp_audio_only.NAME:    _wrap(ytdlp_audio_only),
    innertube_direct.NAME:    _wrap(innertube_direct),
    cobalt.NAME:              _wrap(cobalt),
    piped.NAME:               _wrap(piped),
    invidious.NAME:           _wrap(invidious),
}


def list_methods() -> list[str]:
    """Return all registered method names."""
    return list(METHOD_REGISTRY.keys())
