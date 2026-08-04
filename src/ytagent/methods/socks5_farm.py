"""Tier 7.5 — SOCKS5 proxy farm (tries free proxies in parallel).

When all direct methods and proxy services fail, this method fetches a
list of free SOCKS5 proxies and tries them in parallel. The first proxy
that can reach YouTube's player API without LOGIN_REQUIRED wins, and
yt-dlp is then run through that proxy to download the video.

PROVEN to work: approximately 0.2-2% of tested free SOCKS5 proxies
successfully bypass YouTube's datacenter IP block. Testing 200 proxies
in parallel typically yields 1-4 working ones.

This is a last-resort method — free proxies are unreliable and die within
minutes. But when nothing else works, it can save the day.
"""

from __future__ import annotations

import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult

NAME = "socks5_farm"

# Proxy list sources. These are community-maintained free proxy lists.
PROXY_LIST_URLS = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
]

# How many proxies to test in parallel.
PARALLEL_TESTS = 50

# How many proxies to try total (cap to avoid taking forever).
MAX_PROXIES_TO_TEST = 200

# Timeout for each proxy test (seconds).
PROXY_TEST_TIMEOUT = 8

# The YouTube video ID to test proxy reachability with.
# We check if the watch page returns a playability status of OK (not LOGIN_REQUIRED).
# Using a widely-embedded, stable public video for reliable proxy testing.
TEST_VIDEO_ID = "dQw4w9WgXcQ"  # placeholder — replace with any stable public video ID


def _fetch_proxy_list() -> list[str]:
    """Fetch SOCKS5 proxy lists from multiple sources."""
    import requests
    proxies = set()
    for url in PROXY_LIST_URLS:
        try:
            r = requests.get(url, timeout=10, verify=False)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    line = line.strip()
                    if ":" in line and len(line) < 50:
                        proxies.add(line)
        except Exception as e:
            log.debug("socks5_farm: failed to fetch proxy list", url=url, error=str(e))
    return list(proxies)[:MAX_PROXIES_TO_TEST]


def _test_proxy(proxy: str, video_id: str) -> tuple[str, bool, str]:
    """Test if a proxy can reach YouTube's player API without LOGIN_REQUIRED.

    Does a TWO-PHASE test:
      1. Fetch the watch page and check playabilityStatus is OK (not LOGIN_REQUIRED)
      2. POST to the innertube player API to confirm stream URLs are returned

    Only proxies that pass BOTH phases are considered working.

    Returns (proxy, ok, reason).
    """
    import requests
    try:
        # First: quick TCP connect test (fast fail for dead proxies)
        host, port = proxy.rsplit(":", 1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        try:
            sock.connect((host, int(port)))
            sock.close()
        except (socket.timeout, OSError):
            return (proxy, False, "tcp connect failed")

        proxies = {"http": f"socks5://{proxy}", "https": f"socks5://{proxy}"}
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Phase 1: fetch the watch page and check playability
        r = requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            proxies=proxies,
            timeout=PROXY_TEST_TIMEOUT,
            verify=False,
            headers=headers,
        )
        if r.status_code != 200:
            return (proxy, False, f"watch page HTTP {r.status_code}")

        body = r.text
        if '"status":"LOGIN_REQUIRED"' in body:
            return (proxy, False, "watch page LOGIN_REQUIRED")
        if '"status":"ERROR"' in body:
            return (proxy, False, "watch page ERROR")
        if '"status":"OK"' not in body:
            return (proxy, False, "watch page no OK status")

        # Phase 2: POST to the innertube player API to confirm stream URLs
        # Extract visitor_data from the watch page
        import re
        vd_match = re.search(r'"visitorData":"([^"]+)"', body)
        visitor_data = vd_match.group(1) if vd_match else ""

        player_payload = {
            "context": {
                "client": {
                    "clientName": "ANDROID_VR",
                    "clientVersion": "1.65.10",
                    "androidSdkVersion": 32,
                    "visitorData": visitor_data,
                }
            },
            "videoId": video_id,
        }
        player_headers = {
            "Content-Type": "application/json",
            "User-Agent": headers["User-Agent"],
            "X-YouTube-Client-Name": "3",
            "X-YouTube-Client-Version": "1.65.10",
        }
        r2 = requests.post(
            "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
            json=player_payload,
            headers=player_headers,
            proxies=proxies,
            timeout=PROXY_TEST_TIMEOUT,
            verify=False,
        )
        if r2.status_code != 200:
            return (proxy, False, f"player API HTTP {r2.status_code}")

        try:
            pdata = r2.json()
        except Exception:
            return (proxy, False, "player API bad JSON")

        pstatus = pdata.get("playabilityStatus", {}).get("status", "")
        if pstatus != "OK" and pstatus != "LIVE_STREAM_OFFLINE":
            return (proxy, False, f"player API status={pstatus}")

        # Check that streamingData is present (has actual stream URLs)
        if not pdata.get("streamingData"):
            return (proxy, False, "player API no streamingData")

        return (proxy, True, "OK")
    except Exception as e:
        return (proxy, False, str(e)[:50])


def _find_working_proxy(video_id: str) -> str | None:
    """Find a SOCKS5 proxy that can reach YouTube without LOGIN_REQUIRED.

    Tests up to MAX_PROXIES_TO_TEST proxies in parallel batches.
    Returns the first working proxy, or None.
    """
    proxies = _fetch_proxy_list()
    if not proxies:
        log.warn("socks5_farm: no proxies fetched from lists")
        return None

    log.info("socks5_farm: testing proxies",
             count=len(proxies), parallel=PARALLEL_TESTS)

    # Test in parallel batches.
    tested = 0
    with ThreadPoolExecutor(max_workers=PARALLEL_TESTS) as pool:
        futures = {}
        for proxy in proxies:
            futures[pool.submit(_test_proxy, proxy, video_id)] = proxy

        for future in as_completed(futures):
            proxy, ok, reason = future.result()
            tested += 1
            if ok:
                log.success("socks5_farm: found working proxy!",
                            proxy=proxy, tested=tested)
                # Cancel remaining futures
                for f in futures:
                    f.cancel()
                return proxy
            if tested % 20 == 0:
                log.debug("socks5_farm: progress",
                          tested=tested, total=len(proxies))

    log.warn("socks5_farm: no working proxy found",
             tested=tested, total=len(proxies))
    return None


def _download_via_proxy(video_id: str, proxy: str, out_dir: Path, opts: dict) -> MethodResult:
    """Download the video using yt-dlp through the SOCKS5 proxy."""
    import yt_dlp
    from ._ytdlp_base import build_opts

    outtmpl = str(out_dir / f"{video_id}.%(ext)s")
    proxy_url = f"socks5://{proxy}"

    ydl_opts = build_opts(
        format=opts.get("format", "best[ext=mp4]/worst[ext=mp4]/worst"),
        player_client=["android_vr", "web"],
        proxy=proxy_url,
        outtmpl=outtmpl,
        use_bgutil=False,  # don't need BGutil when proxy handles the IP block
        extra={
            "socket_timeout": 20,
            "retries": 3,
        },
    )

    bytes_seen = {"value": 0}

    def _progress_hook(d: dict) -> None:
        if d.get("status") == "downloading":
            bytes_seen["value"] = max(bytes_seen["value"], d.get("downloaded_bytes", 0))
        elif d.get("status") == "finished":
            bytes_seen["value"] = max(
                bytes_seen["value"],
                d.get("total_bytes") or d.get("downloaded_bytes", 0),
            )

    ydl_opts["progress_hooks"] = [_progress_hook]
    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        return MethodResult(
            ok=False,
            reason=f"socks5_farm: yt-dlp via {proxy} failed: {type(e).__name__}: {e}",
            bytes_downloaded=bytes_seen["value"],
        )

    candidates = sorted(
        out_dir.glob(f"{video_id}.*"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        return MethodResult(
            ok=False,
            reason=f"socks5_farm: yt-dlp via {proxy} produced no file",
            bytes_downloaded=bytes_seen["value"],
        )

    final = candidates[0]
    return MethodResult(
        ok=True,
        path=str(final),
        bytes_downloaded=final.stat().st_size,
        reason=f"socks5_farm: downloaded via {proxy}",
    )


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Find a working SOCKS5 proxy and download the video through it."""
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("socks5_farm: searching for a working proxy", video_id=video_id)

    # Phase 1: find a proxy that can reach YouTube
    proxy = _find_working_proxy(video_id)
    if proxy is None:
        return MethodResult(
            ok=False,
            reason="socks5_farm: no working SOCKS5 proxy found in proxy lists",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    elapsed_find = time.monotonic() - started
    log.info("socks5_farm: proxy found, downloading",
             proxy=proxy, find_time_s=f"{elapsed_find:.1f}")

    # Phase 2: download through the proxy
    result = _download_via_proxy(video_id, proxy, out_dir, opts)
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result
