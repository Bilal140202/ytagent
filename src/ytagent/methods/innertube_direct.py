"""Tier 5 — Direct Innertube API call.

Hand-rolled POST to https://www.youtube.com/youtubei/v1/player with the
TVHTML5 client (research says it's currently PO-token-light). Parses
streamingData.formats and downloads the best mp4 stream URL with requests.

Sub-fallback: if TVHTML5 returns empty/throttled, try ANDROID client before
giving up. No JS interpreter — relies on the client not requiring signature
deciphering.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ..utils.net import make_session, safe_request, DEFAULT_UA

NAME = "innertube_direct"

# As of late 2025 / 2026. These versions are stable enough for our use.
# yt-dlp updates them, but we keep static fallbacks for this method.
INNERTUBE_CLIENTS = {
    "tvhtml5": {
        "context": {
            "client": {
                "clientName": "TVHTML5",
                "clientVersion": "7.20241201.14.00",
                "userAgent": DEFAULT_UA,
            }
        },
        "api_key": "AIzaSyDCU8hByM-4DrUqRUYnGRn-0XZ82gJ_5-I",
    },
    "android": {
        "context": {
            "client": {
                "clientName": "ANDROID",
                "clientVersion": "20.10.38",
                "androidSdkVersion": 30,
                "osName": "Android",
                "osVersion": "11",
            }
        },
        "api_key": "AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w",
    },
    "ios": {
        "context": {
            "client": {
                "clientName": "IOS",
                "clientVersion": "20.10.4",
                "deviceMake": "Apple",
                "deviceModel": "iPhone16,2",
                "osName": "iPhone",
                "osVersion": "17.4.1.21E236",
            }
        },
        "api_key": "AIzaSyB-63vPrdThhKuerbB2N_l7Kwwcxj6yUAc",
    },
}


def _try_client(client_key: str, video_id: str, out_dir: Path, session, proxy: str | None) -> MethodResult:
    """Try a single innertube client. Returns MethodResult."""
    started = time.monotonic()
    client_cfg = INNERTUBE_CLIENTS[client_key]
    api_url = f"https://www.youtube.com/youtubei/v1/player?key={client_cfg['api_key']}"

    payload = {
        "context": client_cfg["context"],
        "videoId": video_id,
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": client_cfg["context"]["client"].get("userAgent", DEFAULT_UA),
        "X-YouTube-Client-Name": _client_name_to_header(client_key),
        "X-YouTube-Client-Version": client_cfg["context"]["client"]["clientVersion"],
        "Origin": "https://www.youtube.com",
        "Referer": f"https://www.youtube.com/watch?v={video_id}",
    }

    resp = safe_request(
        session,
        "POST",
        api_url,
        json=payload,
        headers=headers,
        timeout=15,
    )
    if resp is None:
        return MethodResult(
            ok=False,
            reason=f"innertube_direct/{client_key}: network error",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    if resp.status_code != 200:
        return MethodResult(
            ok=False,
            reason=f"innertube_direct/{client_key}: HTTP {resp.status_code}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        data = resp.json()
    except Exception as e:
        return MethodResult(
            ok=False,
            reason=f"innertube_direct/{client_key}: JSON parse error: {e}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    playability = data.get("playabilityStatus", {})
    status = playability.get("status", "")
    if status not in ("OK", "LIVE_STREAM_OFFLINE"):
        reason = playability.get("reason") or playability.get("messages", [""])[0] or status
        return MethodResult(
            ok=False,
            reason=f"innertube_direct/{client_key}: playability={status} ({reason})",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    streaming = data.get("streamingData", {})
    formats = streaming.get("formats", []) or []
    adaptive = streaming.get("adaptiveFormats", []) or []

    # Prefer muxed mp4 (formats) over adaptive (which would need muxing).
    # Pick the highest-bitrate mp4 with both video and audio.
    candidates = []
    for f in formats:
        mime = f.get("mimeType", "")
        if "mp4" in mime and "video" in mime and "audio" in mime:
            candidates.append(f)
    # If no muxed, try adaptive video+audio pairs (we'd need ffmpeg to mux).
    # For simplicity in this method, only accept muxed mp4.
    # (Muxing is handled by the Piped/Cobalt methods if needed.)

    if not candidates:
        # Try adaptive as a last resort within this method — pick best mp4 video.
        for f in adaptive:
            mime = f.get("mimeType", "")
            if "mp4" in mime and "video" in mime:
                candidates.append(f)

    if not candidates:
        return MethodResult(
            ok=False,
            reason=f"innertube_direct/{client_key}: no mp4 streams in response",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Pick highest bitrate.
    candidates.sort(key=lambda f: f.get("bitrate", 0), reverse=True)
    chosen = candidates[0]
    stream_url = chosen.get("url")
    if not stream_url:
        return MethodResult(
            ok=False,
            reason=f"innertube_direct/{client_key}: stream URL missing (likely needs signature deciphering)",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Download the stream URL with requests streaming.
    ext = "mp4" if "mp4" in chosen.get("mimeType", "") else "webm"
    out_path = out_dir / f"{video_id}.{ext}"
    bytes_downloaded = _stream_to_file(session, stream_url, out_path, proxy=proxy)
    if bytes_downloaded == 0:
        return MethodResult(
            ok=False,
            reason=f"innertube_direct/{client_key}: stream download produced 0 bytes",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    return MethodResult(
        ok=True,
        path=str(out_path),
        duration_ms=int((time.monotonic() - started) * 1000),
        bytes_downloaded=bytes_downloaded,
    )


def _client_name_to_header(client_key: str) -> str:
    """Return the X-YouTube-Client-Name numeric ID for a client_key."""
    return {
        "tvhtml5": "7",
        "android": "3",
        "ios": "5",
        "web": "1",
    }.get(client_key, "1")


def _stream_to_file(session, url: str, out_path: Path, *, proxy: str | None) -> int:
    """Stream a URL to a file in 1MB chunks. Returns bytes written."""
    try:
        with session.get(url, stream=True, timeout=60, verify=False) as r:
            if r.status_code != 200:
                log.warn("innertube_direct stream HTTP", status=r.status_code)
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
        log.warn("innertube_direct stream failed", error=str(e))
        return 0


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Try TVHTML5 then ANDROID then IOS innertube clients in sequence."""
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = make_session(retries=2, backoff=2.0)
    proxy = opts.get("proxy")

    # Try TVHTML5 first (research says it's PO-token-light).
    for client_key in ("tvhtml5", "android", "ios"):
        result = _try_client(client_key, video_id, out_dir, session, proxy)
        if result.ok:
            result.duration_ms = int((time.monotonic() - started) * 1000)
            return result
        log.debug("innertube_direct sub-method failed",
                  client=client_key, reason=result.reason)

    return MethodResult(
        ok=False,
        reason="innertube_direct: all clients failed",
        duration_ms=int((time.monotonic() - started) * 1000),
    )
