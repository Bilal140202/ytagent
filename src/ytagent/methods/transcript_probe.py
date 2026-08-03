"""Tier 0 — Transcript probe (preflight reachability check).

Uses the youtube-transcript-api style endpoint to quickly check if a video
is reachable from this IP without downloading video bytes. Separate rate-limit
bucket. If this 429s, no other tier will help.

This method does NOT download a video file. It returns ok=True if the video
is reachable (so the Orchestrator proceeds to the next tier), or ok=False
if unreachable (so the Orchestrator can bail early).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ..utils.net import make_session, safe_request

NAME = "transcript_probe"


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Probe video reachability via the transcript listing endpoint.

    Returns ok=True (with path=None) if reachable.
    Returns ok=False if unreachable, with a reason that informs the Orchestrator.
    """
    started = time.monotonic()
    opts = opts or {}

    session = make_session(retries=1, backoff=1.0)

    # The simplest reachability check: fetch the watch page and look for
    # "Video unavailable" / "Sign in to confirm". If we get a 200 with the
    # video player present, the video is reachable.
    url = f"https://www.youtube.com/watch?v={video_id}"

    resp = safe_request(session, "GET", url, timeout=10)
    elapsed = int((time.monotonic() - started) * 1000)

    if resp is None:
        return MethodResult(
            ok=False,
            reason="transcript_probe: network error (IP unreachable or DNS failure)",
            duration_ms=elapsed,
        )

    if resp.status_code == 429:
        return MethodResult(
            ok=False,
            reason=f"transcript_probe: HTTP 429 (rate limited; IP is throttled)",
            duration_ms=elapsed,
        )

    if resp.status_code >= 500:
        return MethodResult(
            ok=False,
            reason=f"transcript_probe: HTTP {resp.status_code} (YouTube server error)",
            duration_ms=elapsed,
        )

    if resp.status_code != 200:
        return MethodResult(
            ok=False,
            reason=f"transcript_probe: HTTP {resp.status_code}",
            duration_ms=elapsed,
        )

    body = resp.text or ""

    # Check for known unreachable signals.
    unreachable_signals = [
        '"status":"ERROR"',
        '"status":"UNPLAYABLE"',
        '"status":"LOGIN_REQUIRED"',
        'Video unavailable',
        'This video is private',
        'This video has been removed',
        'Sign in to confirm you',
        'confirm you',
    ]
    for signal in unreachable_signals:
        if signal in body:
            return MethodResult(
                ok=False,
                reason=f"transcript_probe: video unreachable ({signal.strip(chr(34))!r})",
                duration_ms=elapsed,
            )

    # If we got here with a 200 and no error signals, the video is reachable.
    # Quick sanity check that the player is present.
    if '"playerResponse"' in body or '"videoDetails"' in body or 'ytplayer' in body:
        log.debug("transcript_probe: reachable", video_id=video_id, duration_ms=elapsed)
        return MethodResult(
            ok=True,
            path=None,  # this is a probe; no file produced
            reason="reachable",
            duration_ms=elapsed,
        )

    # Ambiguous — proceed optimistically.
    log.debug("transcript_probe: ambiguous, proceeding", video_id=video_id)
    return MethodResult(
        ok=True,
        path=None,
        reason="ambiguous (proceeding optimistically)",
        duration_ms=elapsed,
    )
