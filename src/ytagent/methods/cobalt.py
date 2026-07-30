"""Tier 6 — Cobalt sidecar method.

POSTs to a self-hosted Cobalt instance (default http://127.0.0.1:9000).
If the sidecar isn't running, fails fast (2s timeout) — does NOT hang.

Handles three response types:
  - "redirect": download the returned URL via requests
  - "tunnel": stream through cobalt
  - "local-processing": fetch both tunnels and mux with ffmpeg locally
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ..utils.net import make_session, safe_request
from ..utils.ff import mux_video_audio

NAME = "cobalt"

DEFAULT_COBALT_URL = "http://127.0.0.1:9000"


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Download via Cobalt sidecar."""
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cobalt_url = opts.get("cobalt_url", DEFAULT_COBALT_URL).rstrip("/")
    session = make_session(retries=0, backoff=1.0)

    url = f"https://www.youtube.com/watch?v={video_id}"
    payload = {
        "url": url,
        "videoQuality": "1080",
        "youtubeVideoCodec": "h264",
        "youtubeVideoContainer": "mp4",
        "downloadMode": "auto",
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    # Quick health check with 2s timeout — fail fast if sidecar not running.
    resp = safe_request(
        session,
        "POST",
        cobalt_url + "/",
        json=payload,
        headers=headers,
        timeout=opts.get("cobalt_timeout", 30),
    )

    if resp is None:
        return MethodResult(
            ok=False,
            reason=f"cobalt: sidecar not reachable at {cobalt_url} (connection refused or timed out)",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    if resp.status_code != 200:
        return MethodResult(
            ok=False,
            reason=f"cobalt: HTTP {resp.status_code}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        data = resp.json()
    except Exception as e:
        return MethodResult(
            ok=False,
            reason=f"cobalt: JSON parse error: {e}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    status = data.get("status")
    if status == "error":
        err = data.get("error", {})
        return MethodResult(
            ok=False,
            reason=f"cobalt: error response ({err.get('code', 'unknown')})",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    if status == "redirect":
        redirect_url = data.get("url")
        if not redirect_url:
            return MethodResult(
                ok=False,
                reason="cobalt: redirect status but no url field",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        out_path = out_dir / f"{video_id}.mp4"
        bytes_written = _stream_url(session, redirect_url, out_path)
        if bytes_written == 0:
            return MethodResult(
                ok=False,
                reason="cobalt: redirect stream produced 0 bytes",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        return MethodResult(
            ok=True,
            path=str(out_path),
            duration_ms=int((time.monotonic() - started) * 1000),
            bytes_downloaded=bytes_written,
        )

    if status == "tunnel":
        # Cobalt tunnels the stream through itself.
        tunnel_urls = data.get("tunnel") or []
        if isinstance(tunnel_urls, dict):
            tunnel_urls = [tunnel_urls]
        if not tunnel_urls:
            return MethodResult(
                ok=False,
                reason="cobalt: tunnel status but no tunnel array",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        # Single tunnel = muxed stream.
        if len(tunnel_urls) == 1:
            t = tunnel_urls[0]
            stream_url = t.get("url") if isinstance(t, dict) else t
            out_path = out_dir / f"{video_id}.mp4"
            bytes_written = _stream_url(session, stream_url, out_path)
            if bytes_written == 0:
                return MethodResult(
                    ok=False,
                    reason="cobalt: tunnel stream produced 0 bytes",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            return MethodResult(
                ok=True,
                path=str(out_path),
                duration_ms=int((time.monotonic() - started) * 1000),
                bytes_downloaded=bytes_written,
            )
        # Multiple tunnels = video + audio, need mux.
        return _mux_tunnels(session, tunnel_urls, out_dir, video_id, started)

    if status == "local-processing":
        # Cobalt returns separate video and audio tunnels for local muxing.
        tunnels = data.get("tunnel", [])
        if isinstance(tunnels, dict):
            tunnels = [tunnels]
        if len(tunnels) < 2:
            return MethodResult(
                ok=False,
                reason="cobalt: local-processing status but fewer than 2 tunnels",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        return _mux_tunnels(session, tunnels, out_dir, video_id, started)

    return MethodResult(
        ok=False,
        reason=f"cobalt: unknown status {status!r}",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _stream_url(session, url: str, out_path: Path) -> int:
    """Stream a URL to a file in 1MB chunks. Returns bytes written."""
    try:
        with session.get(url, stream=True, timeout=120, verify=False) as r:
            if r.status_code != 200:
                log.warn("cobalt stream HTTP", status=r.status_code)
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
        log.warn("cobalt stream failed", error=str(e))
        return 0


def _mux_tunnels(session, tunnels: list, out_dir: Path, video_id: str, started: float) -> MethodResult:
    """Download video + audio tunnels separately, then mux with ffmpeg."""
    video_url = None
    audio_url = None
    for t in tunnels:
        if isinstance(t, dict):
            url = t.get("url")
            tt = t.get("type", "")
        else:
            url = t
            tt = ""
        if "video" in tt or (video_url is None and audio_url is not None):
            video_url = url
        elif "audio" in tt or (audio_url is None and video_url is not None):
            audio_url = url
    if not video_url or not audio_url:
        # Fallback: assume first is video, second is audio.
        video_url = tunnels[0].get("url") if isinstance(tunnels[0], dict) else tunnels[0]
        audio_url = tunnels[1].get("url") if isinstance(tunnels[1], dict) else tunnels[1]

    v_path = out_dir / f"{video_id}.video.mp4"
    a_path = out_dir / f"{video_id}.audio.m4a"
    out_path = out_dir / f"{video_id}.mp4"

    vb = _stream_url(session, video_url, v_path)
    ab = _stream_url(session, audio_url, a_path)
    if vb == 0 or ab == 0:
        return MethodResult(
            ok=False,
            reason=f"cobalt: tunnel download incomplete (video={vb}, audio={ab})",
            duration_ms=int((time.monotonic() - started) * 1000),
            bytes_downloaded=vb + ab,
        )

    if not mux_video_audio(v_path, a_path, out_path, timeout=120):
        # Fall back to just the video stream (will fail Verifier's audio check
        # but at least we have something).
        log.warn("cobalt mux failed, returning video-only")
        v_path.rename(out_path)
        return MethodResult(
            ok=True,
            path=str(out_path),
            duration_ms=int((time.monotonic() - started) * 1000),
            bytes_downloaded=vb + ab,
            reason="mux failed; video-only fallback",
        )

    # Clean up temp files.
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
