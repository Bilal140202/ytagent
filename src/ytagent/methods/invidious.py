"""Tier 8 — Invidious `local=true` proxy bypass (WORKS for blocked IPs).

This is the BREAKTHROUGH method that bypasses YouTube's datacenter IP block.
Instead of hitting Invidious's /latest_version redirect (which just redirects
to googlevideo.com — blocked from our IP), we use the `local=true` parameter
which tells Invidious to proxy the video stream through ITS OWN server.

The Invidious instance has a residential/non-blocked IP, so it can fetch
from googlevideo.com. We then download from the Invidious instance, which
acts as a middleman.

PROVEN to work for the previously-blocked video

Limitation: 360p muxed MP4 only (itag=18). For higher quality, use the
cobalt_community method which can get 720p.

Instance `invidious.f5.si` is the only one currently supporting local=true
proxying. Other instances disable it or return 403.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ..utils.net import make_session, safe_request

NAME = "invidious"

# Instances that support local=true proxying (Invidious fetches from
# googlevideo and streams to us). Most instances disable this; the ones
# listed here have it enabled as of 2026-08.
DEFAULT_INSTANCES = [
    "https://invidious.f5.si",        # PROVEN WORKING — 360p via local=true
    "https://yewtu.be",                # sometimes works, often Cloudflare-challenged
    "https://invidious.nerdvpn.de",   # occasionally works
    "https://inv.nadeko.net",         # occasionally works
]


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Try each Invidious instance with local=true proxy bypass.

    The local=true parameter is the key: it makes Invidious proxy the
    googlevideo stream through its own IP, bypassing our datacenter block.
    """
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    instances = opts.get("invidious_instances", DEFAULT_INSTANCES)
    session = make_session(retries=1, backoff=2.0)

    for base in instances:
        base = base.rstrip("/")
        result = _try_instance_local(base, video_id, out_dir, session, started)
        if result.ok:
            return result
        log.debug("invidious instance failed",
                  instance=base, reason=result.reason)

    return MethodResult(
        ok=False,
        reason=f"invidious: all {len(instances)} instances failed (local=true proxy)",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _try_instance_local(
    base: str,
    video_id: str,
    out_dir: Path,
    session,
    started: float,
) -> MethodResult:
    """Try a single Invidious instance with local=true proxying."""
    # itag=18 = 360p muxed MP4 (H.264 + AAC). This is the most universally
    # supported format and the one most likely to be proxied successfully.
    url = f"{base}/latest_version?id={video_id}&itag=18&local=true"

    out_path = out_dir / f"{video_id}.mp4"
    bytes_written = _stream_redirect(session, url, out_path)
    if bytes_written > 0:
        return MethodResult(
            ok=True,
            path=str(out_path),
            duration_ms=int((time.monotonic() - started) * 1000),
            bytes_downloaded=bytes_written,
            reason=f"invidious: {base} (local=true proxy, 360p)",
        )
    return MethodResult(
        ok=False,
        reason=f"invidious/{base}: local=true proxy produced 0 bytes",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _stream_redirect(session, url: str, out_path: Path) -> int:
    """Stream a URL to a file in 1MB chunks. Returns bytes written.

    The local=true parameter makes Invidious stream the video through its
    own server instead of redirecting to googlevideo.com. This means:
    - Content-Type should be video/mp4 (not text/html)
    - The stream is proxied through Invidious's IP (residential/non-blocked)
    """
    try:
        with session.get(url, stream=True, timeout=(15, 300), verify=False, allow_redirects=True) as r:
            if r.status_code != 200:
                log.debug("invidious stream HTTP",
                          status=r.status_code, url=url[:80])
                return 0
            ct = r.headers.get("Content-Type", "")
            if "text/html" in ct:
                # Got an HTML error page instead of a video stream.
                log.debug("invidious returned HTML", url=url[:80])
                return 0
            if "video" not in ct and "octet-stream" not in ct:
                log.debug("invidious returned non-video content-type",
                          ct=ct, url=url[:80])
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
