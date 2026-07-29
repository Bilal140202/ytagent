"""Shared yt-dlp options builder + BGutil POT provider auto-loading.

All yt-dlp-based method modules import this to avoid duplicating the
cloud-friendly option block.

CRITICAL: This module sets YTDLP_PLUGIN_DIRS before yt_dlp is imported
anywhere in the process, so the BGutil POT provider plugin is auto-loaded.
This is what enables downloads from datacenter IPs that YouTube would
otherwise block with "Sign in to confirm you're not a bot" (LOGIN_REQUIRED).

The BGutil server source must be present at /home/z/bgutil-ytdlp-pot-provider/server/
(see scripts/install_sidecars.sh or the manual clone+build steps in README.md).
The HTTP server at 127.0.0.1:4416 is preferred if running; otherwise the
script-node fallback (spawning `node generate_once.js` per call) is used.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

# --- Auto-load the BGutil POT provider plugin ---
# yt_dlp reads YTDLP_PLUGIN_DIRS at import time. We set it before any
# `import yt_dlp` happens anywhere in the process.

_BGUTIL_SERVER_PATH = Path("/home/z/bgutil-ytdlp-pot-provider/server")
_PLUGIN_DIRS = []

# The bgutil-ytdlp-pot-provider pip package installs a yt_dlp_plugins dir.
# Find it and add to YTDLP_PLUGIN_DIRS.
try:
    import bgutil_ytdlp_pot_provider as _bgutil_pkg
    _pkg_dir = Path(_bgutil_pkg.__file__).parent
    # The plugin entry point is typically in a yt_dlp_plugins subdir.
    for candidate in [_pkg_dir / "yt_dlp_plugins", _pkg_dir.parent / "yt_dlp_plugins"]:
        if candidate.exists():
            _PLUGIN_DIRS.append(str(candidate))
            break
except ImportError:
    pass

# Also add the venv's yt_dlp_plugins dir if present.
_venv_plugins = Path("/home/z/.venv/lib/python3.12/site-packages/yt_dlp_plugins")
if _venv_plugins.exists():
    _PLUGIN_DIRS.append(str(_venv_plugins))

# Set the env var if we found any plugin dirs.
if _PLUGIN_DIRS:
    existing = os.environ.get("YTDLP_PLUGIN_DIRS", "")
    if existing:
        all_dirs = existing + os.pathsep + os.pathsep.join(_PLUGIN_DIRS)
    else:
        all_dirs = os.pathsep.join(_PLUGIN_DIRS)
    os.environ["YTDLP_PLUGIN_DIRS"] = all_dirs

# Cloud-friendly base options, applied to every yt-dlp invocation.
# See techstack.md and the research report for justification of each.
BASE_OPTS: dict[str, Any] = {
    # Quiet output (we use progress_hooks instead).
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "ignoreerrors": True,
    # Cloud: no cache, no cookies, no cert check.
    "nocheckcertificate": True,
    "nocache_dir": True,
    "no_cookies": True,
    # Network resilience.
    "socket_timeout": 30,
    "retries": 10,
    "fragment_retries": 10,
    "extractor_retries": 3,
    "file_access_retries": 10,
    "retry_sleep_functions": {
        "extractor": "linear=5::30",
        "fragment": "linear=5::30",
        "http": "linear=5::30",
    },
    # Output behavior.
    "merge_output_format": "mp4",
    "postprocessor_args": {
        "ffmpeg": ["-movflags", "+faststart"],
    },
    # Don't write extra files.
    "writethumbnail": False,
    "writeinfojson": False,
    "writedescription": False,
    "writesubtitles": False,
    "writeautomaticsub": False,
}


def bgutil_http_server_running() -> bool:
    """Check if the BGutil HTTP server is reachable on 127.0.0.1:4416."""
    import requests
    try:
        r = requests.get("http://127.0.0.1:4416/ping", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def build_opts(
    *,
    format: str | None = None,
    player_client: list[str] | None = None,
    proxy: str | None = None,
    outtmpl: str | None = None,
    use_bgutil: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a yt-dlp options dict starting from BASE_OPTS.

    Args:
        format: yt-dlp format string.
        player_client: list of innertube clients to try (e.g. ['android_vr']).
        proxy: HTTP proxy URL.
        outtmpl: output template.
        use_bgutil: if True (default), configure the BGutil POT provider.
                    This is essential for datacenter IPs.
        extra: additional opts to merge in last.
    """
    opts = dict(BASE_OPTS)
    if format is not None:
        opts["format"] = format

    extractor_args: dict[str, Any] = {}
    if player_client is not None:
        extractor_args["youtube"] = {"player_client": player_client}

    # Configure BGutil POT provider.
    if use_bgutil:
        bgutil_args: dict[str, Any] = {}
        if bgutil_http_server_running():
            # Use the HTTP server (faster, cached tokens).
            bgutil_args["base_url"] = "http://127.0.0.1:4416"
        else:
            # Use script-node mode (spawns node per call, slower but works
            # without the HTTP sidecar).
            if _BGUTIL_SERVER_PATH.exists():
                bgutil_args["script_path"] = str(
                    _BGUTIL_SERVER_PATH / "build" / "generate_once.js"
                )
        if bgutil_args:
            extractor_args["youtubepot-bgutilhttp"] = bgutil_args
            extractor_args["youtubepot-bgutilscript-node"] = {
                "server_home": str(_BGUTIL_SERVER_PATH)
            }

    if extractor_args:
        opts["extractor_args"] = extractor_args

    if proxy is not None:
        opts["proxy"] = proxy
    if outtmpl is not None:
        opts["outtmpl"] = outtmpl
    if extra:
        opts.update(extra)
    return opts
