"""ffmpeg / ffprobe wrappers with timeouts and structured output.

Used by:
  - Verifier (ffprobe to inspect a downloaded file)
  - Methods that need to mux separate video+audio streams (piped, sometimes cobalt)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .. import log


def find_binary(name: str) -> str | None:
    """Return the path to a binary, or None if not on PATH."""
    return shutil.which(name)


def ffprobe_available() -> bool:
    return find_binary("ffprobe") is not None


def ffmpeg_available() -> bool:
    return find_binary("ffmpeg") is not None


def probe(path: Path, *, timeout: int = 10) -> dict | None:
    """Run ffprobe on `path`, return parsed JSON, or None on failure.

    Never raises. Logs warnings on failure.
    """
    ffprobe = find_binary("ffprobe")
    if ffprobe is None:
        log.warn("ffprobe not found on PATH", path=str(path))
        return None

    cmd = [
        ffprobe,
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-print_format", "json",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warn("ffprobe timed out", path=str(path), timeout=timeout)
        return None
    except Exception as e:
        log.warn("ffprobe failed", path=str(path), error=str(e))
        return None

    if proc.returncode != 0:
        log.warn("ffprobe non-zero exit",
                 path=str(path), returncode=proc.returncode, stderr=proc.stderr[:500])
        return None

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        log.warn("ffprobe returned invalid JSON", path=str(path), error=str(e))
        return None


def mux_video_audio(
    video_path: Path,
    audio_path: Path,
    out_path: Path,
    *,
    timeout: int = 120,
) -> bool:
    """Mux a video-only and an audio-only file into a single MP4.

    Uses stream copy (no re-encode) for speed. Adds +faststart.
    Returns True on success, False on failure. Never raises.
    """
    ffmpeg = find_binary("ffmpeg")
    if ffmpeg is None:
        log.warn("ffmpeg not found on PATH; cannot mux")
        return False

    cmd = [
        ffmpeg,
        "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        log.warn("ffmpeg mux timed out", timeout=timeout)
        return False
    except Exception as e:
        log.warn("ffmpeg mux failed", error=str(e))
        return False

    if proc.returncode != 0:
        log.warn("ffmpeg mux non-zero exit",
                 returncode=proc.returncode, stderr=proc.stderr[:500])
        return False

    return out_path.exists() and out_path.stat().st_size > 0
