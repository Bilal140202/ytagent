"""Tier 2 — yt-dlp with IOS client (HLS).

Sometimes dodges blocks that affect the WEB client. Returns HLS m3u8 which
yt-dlp handles (segment fetching).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ._ytdlp_base import build_opts

NAME = "ytdlp_ios"

DEFAULT_FORMAT = "best[ext=mp4]/best"


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Download via yt-dlp with player_client=[ios]."""
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outtmpl = str(out_dir / f"{video_id}.%(ext)s")
    ydl_opts = build_opts(
        format=opts.get("format", DEFAULT_FORMAT),
        player_client=["ios"],
        proxy=opts.get("proxy"),
        outtmpl=outtmpl,
        use_bgutil=True,
    )

    bytes_seen = {"value": 0}

    def _progress_hook(d: dict) -> None:
        if d.get("status") == "downloading":
            bytes_seen["value"] = max(
                bytes_seen["value"], d.get("downloaded_bytes", 0)
            )
        elif d.get("status") == "finished":
            bytes_seen["value"] = max(
                bytes_seen["value"],
                d.get("total_bytes") or d.get("downloaded_bytes", 0),
            )

    ydl_opts["progress_hooks"] = [_progress_hook]
    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        elapsed = int((time.monotonic() - started) * 1000)
        log.warn("ytdlp_ios failed", video_id=video_id, error=str(e), duration_ms=elapsed)
        return MethodResult(
            ok=False,
            reason=f"ytdlp_ios error: {type(e).__name__}: {e}",
            duration_ms=elapsed,
            bytes_downloaded=bytes_seen["value"],
        )

    elapsed = int((time.monotonic() - started) * 1000)
    candidates = sorted(
        out_dir.glob(f"{video_id}.*"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        return MethodResult(
            ok=False,
            reason="ytdlp_ios: no output file produced",
            duration_ms=elapsed,
            bytes_downloaded=bytes_seen["value"],
        )

    final = candidates[0]
    return MethodResult(
        ok=True,
        path=str(final),
        duration_ms=elapsed,
        bytes_downloaded=final.stat().st_size,
    )
