"""Method base interface — the contract every download method implements.

A method is a callable: download(video_id, out_dir, opts) -> MethodResult
It never raises. It writes only inside out_dir. It respects opts['timeout'].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class MethodResult:
    """Result of a single download method attempt."""

    ok: bool
    path: str | None = None
    reason: str | None = None
    duration_ms: int = 0
    bytes_downloaded: int = 0
    method: str = ""              # filled by Orchestrator from METHOD_REGISTRY
    extra: dict[str, Any] = field(default_factory=dict)


class Method(Protocol):
    """Protocol every method module implements."""

    NAME: str

    def download(
        self,
        video_id: str,
        out_dir: Path,
        opts: dict[str, Any] | None = None,
    ) -> MethodResult:
        ...


def default_opts(**overrides: Any) -> dict[str, Any]:
    """Return the default opts dict with optional overrides."""
    opts: dict[str, Any] = {
        "timeout": 180,           # per-method hard cap in seconds
        "format": None,           # method-specific default if None
        "proxy": None,            # HTTP proxy URL (e.g. WARP sidecar)
        "verbose": False,
    }
    opts.update(overrides)
    return opts
