"""Tier 5.5 — Cobalt community instances (no self-hosting required).

Hits the public cobalt.directory-listed instances in order. The relay
api.cobalt.liubquanti.click is the only one that doesn't require JWT
and works for ~2 calls per source IP before IP-blocking.

PROVEN to bypass YouTube's datacenter IP block. Successfully downloaded
previously-blocked videos that failed on every direct method (yt-dlp,
innertube direct, BGutil POT, Piped, Invidious).

For sustained use, self-host Cobalt on a residential-IP VM with WARP
(see BYPASS-1 report recommendation #2).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ..utils.net import make_session, safe_request

# Note: log.warning doesn't exist in our logger; use log.warn

NAME = "cobalt_community"

# Hardcoded fallback if cobalt.directory is unreachable.
# Order: relay first (no JWT required), then JWT-required instances.
DEFAULT_INSTANCES = [
    "https://api.cobalt.liubquanti.click",  # relay, no JWT, IP-blocks after ~2 calls
    "https://api-cobalt.eversiege.network",
    "https://api.qwkuns.me",
    "https://apicobalt.mgytr.top",
    "https://nuko-c.meowing.de",
    "https://bergung-api.hoffnungfuerdiezukunft.net",
    "https://subito-c.meowing.de",
    "https://kitty.tame.gg",
    "https://cobalt.alpha.wolfy.love",
    "https://cobalt.omega.wolfy.love",
]


def fetch_live_instances(session) -> list[str]:
    """Pull the live list of YouTube-supporting cobalt instances from cobalt.directory."""
    try:
        r = safe_request(
            session,
            "GET",
            "https://cobalt.directory/api/working?type=api",
            timeout=10,
        )
        if r and r.status_code == 200:
            data = r.json()
            live = data.get("data", {}).get("youtube", [])
            # Always put the relay first — it's the only no-JWT instance that
            # currently works for us.
            relay = "https://api.cobalt.liubquanti.click"
            return [relay] + [i for i in live if i != relay]
    except Exception as e:
        log.warn(f"cobalt_community: could not fetch live list: {e}")
    return DEFAULT_INSTANCES


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Try each cobalt community instance in turn until one succeeds."""
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = make_session(retries=0, backoff=1.0)
    instances = fetch_live_instances(session)
    url = f"https://www.youtube.com/watch?v={video_id}"

    payload = {
        "url": url,
        "videoQuality": opts.get("videoQuality", "720"),
        "youtubeVideoCodec": "h264",
        "youtubeVideoContainer": "mp4",
        "downloadMode": "auto",
        "filenameStyle": "basic",
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    for inst in instances:
        log.info(f"cobalt_community: trying {inst}")
        r = safe_request(
            session,
            "POST",
            inst + "/",
            json=payload,
            headers=headers,
            timeout=opts.get("api_timeout", 30),
        )
        if not r or r.status_code != 200:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        status = data.get("status")
        if status not in ("tunnel", "redirect"):
            err = data.get("error", {})
            log.warn(
                f"cobalt_community: {inst} -> {err.get('code', '?')} "
                f"({str(err.get('context', ''))[:120]})"
            )
            continue

        tunnel_url = data.get("url")
        if not tunnel_url:
            continue

        out_path = out_dir / f"{video_id}.mp4"
        try:
            with session.get(tunnel_url, stream=True, timeout=600) as up:
                up.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in up.iter_content(1 << 20):
                        if chunk:
                            f.write(chunk)
            size = out_path.stat().st_size
            if size < 100_000:
                log.warn(
                    f"cobalt_community: {inst} produced only {size} bytes (too small)"
                )
                out_path.unlink(missing_ok=True)
                continue
            return MethodResult(
                ok=True,
                reason=f"cobalt_community: {inst} -> {size:,} bytes",
                duration_ms=int((time.monotonic() - started) * 1000),
                path=str(out_path),
                bytes_downloaded=size,
            )
        except Exception as e:
            log.warn(
                f"cobalt_community: tunnel download from {inst} failed: {e}"
            )
            out_path.unlink(missing_ok=True)
            continue

    return MethodResult(
        ok=False,
        reason=(
            "cobalt_community: all instances failed "
            "(relay IP-blocked after ~2 calls, or JWT required by all others; "
            "self-host Cobalt on Oracle Free Tier + WARP for sustained use)"
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
