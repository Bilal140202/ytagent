"""Tier 8 — Invidious `latest_version` redirect.

Last-resort method. Yields 360p muxed MP4 via an Invidious instance's
redirect endpoint. Often flaky but worth trying when everything else fails.

Endpoint: GET https://<instance>/latest_version?id=<ID>&itag=18
(itag=18 = 360p muxed MP4)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ..utils.net import make_session, safe_request

NAME = "invidious"

DEFAULT_INSTANCES = [
    "https://yewtu.be",
    "https://invidious.nerdvpn.de",
    "https://inv.nadeko.net",
    "https://invidious.privacydev.net",
]


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Try each Invidious instance in order with itag=18 (360p muxed mp4)."""
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    instances = opts.get("invidious_instances", DEFAULT_INSTANCES)
    session = make_session(retries=1, backoff=2.0)

    for base in instances:
        base = base.rstrip("/")
        result = _try_instance(base, video_id, out_dir, session, started)
        if result.ok:
            return result
        log.debug("invidious instance failed", instance=base, reason=result.reason)

    return MethodResult(
        ok=False,
        reason=f"invidious: all {len(instances)} instances failed",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _try_instance(
    base: str,
    video_id: str,
    out_dir: Path,
    session,
    started: float,
) -> MethodResult:
    """Try a single Invidious instance."""
    # itag=18 = 360p muxed MP4 (H.264 + AAC).
    url = f"{base}/latest_version?id={video_id}&itag=18"

    out_path = out_dir / f"{video_id}.mp4"
    bytes_written = _stream_redirect(session, url, out_path)
    if bytes_written > 0:
        return MethodResult(
            ok=True,
            path=str(out_path),
            duration_ms=int((time.monotonic() - started) * 1000),
            bytes_downloaded=bytes_written,
        )
    return MethodResult(
        ok=False,
        reason=f"invidious/{base}: stream produced 0 bytes (instance may not have video cached)",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _stream_redirect(session, url: str, out_path: Path) -> int:
    """Stream a redirect URL to a file in 1MB chunks. Returns bytes written."""
    try:
        with session.get(url, stream=True, timeout=60, verify=False, allow_redirects=True) as r:
            if r.status_code != 200:
                log.debug("invidious stream HTTP", status=r.status_code, url=url)
                return 0
            ct = r.headers.get("Content-Type", "")
            if "text/html" in ct:
                # Got an HTML error page instead of a video stream.
                log.debug("invidious returned HTML", url=url)
                return 0
            out_path.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with out_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
            return written
    except Exception as e:
        log.warn("invidious stream failed", error=str(e))
        return 0
