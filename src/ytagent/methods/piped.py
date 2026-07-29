"""Tier 7 — Piped API with multi-instance rotation.

Tries each known-good Piped instance in order. If one 429s or 5xxs, tries
the next. Muxes video+audio with ffmpeg if only separate streams are
available.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ..utils.net import make_session, safe_request
from ..utils.ff import mux_video_audio

NAME = "piped"

# As of late 2025. These instances are community-maintained and may go down.
# The Truth Agent will demote this method after consecutive failures.
DEFAULT_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.r4fo.com",
]


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Try each Piped instance in order until one succeeds."""
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    instances = opts.get("piped_instances", DEFAULT_INSTANCES)
    session = make_session(retries=1, backoff=2.0)

    for base in instances:
        base = base.rstrip("/")
        result = _try_instance(base, video_id, out_dir, session, started)
        if result.ok:
            return result
        log.debug("piped instance failed", instance=base, reason=result.reason)

    return MethodResult(
        ok=False,
        reason=f"piped: all {len(instances)} instances failed",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _try_instance(
    base: str,
    video_id: str,
    out_dir: Path,
    session,
    started: float,
) -> MethodResult:
    """Try a single Piped instance."""
    streams_url = f"{base}/streams/{video_id}"
    resp = safe_request(session, "GET", streams_url, timeout=15)

    if resp is None:
        return MethodResult(ok=False, reason=f"piped/{base}: network error")
    if resp.status_code == 429:
        return MethodResult(ok=False, reason=f"piped/{base}: 429 rate limited")
    if resp.status_code >= 500:
        return MethodResult(ok=False, reason=f"piped/{base}: HTTP {resp.status_code}")
    if resp.status_code != 200:
        return MethodResult(ok=False, reason=f"piped/{base}: HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception as e:
        return MethodResult(ok=False, reason=f"piped/{base}: JSON error: {e}")

    if data.get("error"):
        return MethodResult(ok=False, reason=f"piped/{base}: {data['error']}")

    video_streams = data.get("videoStreams", []) or []
    audio_streams = data.get("audioStreams", []) or []

    # Preferred: a muxed mp4 video stream (videoOnly=false).
    muxed = [v for v in video_streams if not v.get("videoOnly", True) and "mp4" in v.get("mimeType", "")]
    if muxed:
        # Pick highest quality muxed.
        muxed.sort(key=lambda v: v.get("quality", 0), reverse=True)
        chosen = muxed[0]
        out_path = out_dir / f"{video_id}.mp4"
        bytes_written = _stream_url(session, chosen["url"], out_path)
        if bytes_written > 0:
            return MethodResult(
                ok=True,
                path=str(out_path),
                duration_ms=int((time.monotonic() - started) * 1000),
                bytes_downloaded=bytes_written,
            )

    # Otherwise: separate video and audio, need muxing.
    if video_streams and audio_streams:
        # Pick best mp4 video-only.
        v_mp4 = [v for v in video_streams if v.get("videoOnly", True) and "mp4" in v.get("mimeType", "")]
        v_mp4.sort(key=lambda v: v.get("quality", 0), reverse=True)
        if v_mp4:
            v = v_mp4[0]
            # Pick best m4a audio.
            a_m4a = [a for a in audio_streams if "mp4" in a.get("mimeType", "") or "m4a" in a.get("mimeType", "")]
            a_m4a.sort(key=lambda a: a.get("bitrate", 0), reverse=True)
            if a_m4a:
                a = a_m4a[0]
                v_path = out_dir / f"{video_id}.video.mp4"
                a_path = out_dir / f"{video_id}.audio.m4a"
                out_path = out_dir / f"{video_id}.mp4"
                vb = _stream_url(session, v["url"], v_path)
                ab = _stream_url(session, a["url"], a_path)
                if vb > 0 and ab > 0:
                    if mux_video_audio(v_path, a_path, out_path, timeout=120):
                        try:
                            v_path.unlink(missing_ok=True)
                            a_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                        return MethodResult(
                            ok=True,
                            path=str(out_path),
                            duration_ms=int((time.monotonic() - started) * 1000),
                            bytes_downloaded=vb + ab,
                        )

    return MethodResult(
        ok=False,
        reason=f"piped/{base}: no usable streams in response",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _stream_url(session, url: str, out_path: Path) -> int:
    """Stream a URL to a file in 1MB chunks. Returns bytes written."""
    try:
        with session.get(url, stream=True, timeout=120, verify=False) as r:
            if r.status_code != 200:
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
        log.warn("piped stream failed", error=str(e))
        return 0
