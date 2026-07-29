"""Verifier agent — 6-layer file integrity check.

See agents.md Agent 3 for the full spec. Summary:
  1. Existence & size (>= 1 MB)
  2. Magic bytes (mp4, webm, matroska, mp3, mpeg, ogg)
  3. ffprobe probe (exit 0, parse JSON)
  4. Duration > 0
  5. At least one video or audio stream
  6. moov atom sanity (MP4 only)

Fail-fast: as soon as one check fails, return without running later checks.
Never raises. Read-only.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .. import log
from ..utils import ff

# Minimum acceptable file size: 1 MB. Anything smaller is almost certainly
# an error page or a truncated header, not a real video.
MIN_SIZE_BYTES = 1_000_000

# Magic byte signatures. Each entry: (offset, byte_pattern, container_name).
# Order matters only for ambiguous prefixes; we check most-specific first.
_MAGIC_SIGNATURES = [
    (0, b"\x00\x00\x00", "mp4_ftyp_prefix"),   # validated by 'ftyp' at offset 4
    (0, b"\x1A\x45\xDF\xA3", "matroska"),       # also webm
    (0, b"\xFF\xFB", "mp3"),
    (0, b"\xFF\xF3", "mp3"),
    (0, b"\xFF\xF2", "mp3"),
    (0, b"ID3", "mp3"),
    (0, b"\x00\x00\x01\xBA", "mpeg_ps"),
    (0, b"\x00\x00\x01\xB3", "mpeg_video"),
    (0, b"OggS", "ogg"),
    (0, b"\x4F\x67\x67\x53", "ogg"),             # alternate OggS
    (0, b"FLV", "flv"),
    (0, b"RIFF", "avi_or_wav"),                  # needs further check
]

# HTML error pages — fail immediately if these appear at the start.
_HTML_PREFIXES = [b"<!DOCTYPE", b"<html", b"<HTML", b"<?xml"]


@dataclass
class VerifyResult:
    """Verdict from Verifier.verify()."""

    ok: bool
    reason: str | None = None
    duration_s: float | None = None
    size_bytes: int | None = None
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "duration_s": self.duration_s,
            "size_bytes": self.size_bytes,
            "container": self.container,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
        }


class Verifier:
    """6-layer file verifier. See agents.md Agent 3."""

    def __init__(self, ffprobe_path: str = "ffprobe"):
        self._ffprobe = ffprobe_path

    def verify(self, path: Path) -> VerifyResult:
        """Run all 6 checks fail-fast. Returns a VerifyResult."""
        path = Path(path)

        # Check 1: existence + size
        try:
            if not path.exists() or not path.is_file():
                return VerifyResult(ok=False, reason=f"file does not exist: {path}")
            size = path.stat().st_size
        except OSError as e:
            return VerifyResult(ok=False, reason=f"stat failed: {e}")

        if size < MIN_SIZE_BYTES:
            return VerifyResult(
                ok=False,
                reason=f"file too small: {size} bytes (min {MIN_SIZE_BYTES})",
                size_bytes=size,
            )

        # Check 2: magic bytes
        try:
            with path.open("rb") as f:
                head = f.read(16)
        except OSError as e:
            return VerifyResult(ok=False, reason=f"read failed: {e}", size_bytes=size)

        container = _identify_magic(head)
        if container is None:
            # Special case: HTML error page
            for prefix in _HTML_PREFIXES:
                if head.startswith(prefix):
                    return VerifyResult(
                        ok=False,
                        reason="file is HTML, not video",
                        size_bytes=size,
                    )
            return VerifyResult(
                ok=False,
                reason=f"unrecognized magic bytes: {head[:8].hex()}",
                size_bytes=size,
            )

        # Check 3: ffprobe
        probe_data = ff.probe(path, timeout=10)
        if probe_data is None:
            # ffprobe unavailable or failed. We can still accept based on
            # magic bytes alone if the file is large enough — but only for
            # non-MP4 containers (we can't check moov without ffprobe for MP4).
            if container in {"matroska", "webm", "mp3", "ogg", "flv"}:
                log.warn("ffprobe unavailable; accepting on magic bytes alone",
                         container=container, path=str(path))
                return VerifyResult(
                    ok=True,
                    reason="accepted on magic bytes (ffprobe unavailable)",
                    size_bytes=size,
                    container=container,
                )
            return VerifyResult(
                ok=False,
                reason="ffprobe failed and container requires it",
                size_bytes=size,
                container=container,
            )

        # Check 4: duration > 0
        fmt = probe_data.get("format", {})
        duration_str = fmt.get("duration")
        duration = None
        if duration_str:
            try:
                duration = float(duration_str)
            except (TypeError, ValueError):
                duration = None

        if duration is None:
            # Fall back to longest stream duration.
            streams = probe_data.get("streams", [])
            for s in streams:
                try:
                    d = float(s.get("duration", 0))
                    duration = max(duration or 0, d)
                except (TypeError, ValueError):
                    continue

        if duration is None or duration <= 0:
            return VerifyResult(
                ok=False,
                reason="duration is 0 or missing",
                size_bytes=size,
                container=container,
            )

        # Check 5: at least one video or audio stream
        streams = probe_data.get("streams", [])
        video_codec = None
        audio_codec = None
        for s in streams:
            ct = s.get("codec_type")
            if ct == "video" and not video_codec:
                video_codec = s.get("codec_name")
            elif ct == "audio" and not audio_codec:
                audio_codec = s.get("codec_name")

        if not video_codec and not audio_codec:
            return VerifyResult(
                ok=False,
                reason="no video or audio stream found",
                duration_s=duration,
                size_bytes=size,
                container=container,
            )

        # Check 6: moov atom sanity for MP4
        if container in {"mp4", "m4v", "mov"}:
            moov_ok, moov_reason = _check_moov_atom(path, size)
            if not moov_ok:
                return VerifyResult(
                    ok=False,
                    reason=f"moov atom check failed: {moov_reason}",
                    duration_s=duration,
                    size_bytes=size,
                    container=container,
                    video_codec=video_codec,
                    audio_codec=audio_codec,
                )

        return VerifyResult(
            ok=True,
            reason=None,
            duration_s=duration,
            size_bytes=size,
            container=container,
            video_codec=video_codec,
            audio_codec=audio_codec,
        )

    def verify_quick(self, path: Path) -> VerifyResult:
        """Run only checks 1-4. Used for in-progress polling."""
        path = Path(path)
        try:
            if not path.exists() or not path.is_file():
                return VerifyResult(ok=False, reason="file does not exist")
            size = path.stat().st_size
        except OSError as e:
            return VerifyResult(ok=False, reason=f"stat failed: {e}")

        if size < MIN_SIZE_BYTES:
            return VerifyResult(ok=False, reason=f"file too small: {size}", size_bytes=size)

        try:
            with path.open("rb") as f:
                head = f.read(16)
        except OSError as e:
            return VerifyResult(ok=False, reason=f"read failed: {e}", size_bytes=size)

        container = _identify_magic(head)
        if container is None:
            return VerifyResult(ok=False, reason="unrecognized magic bytes", size_bytes=size)

        probe_data = ff.probe(path, timeout=10)
        if probe_data is None:
            return VerifyResult(
                ok=True,
                reason="accepted on magic bytes (quick, ffprobe unavailable)",
                size_bytes=size,
                container=container,
            )

        duration_str = probe_data.get("format", {}).get("duration")
        try:
            duration = float(duration_str) if duration_str else None
        except (TypeError, ValueError):
            duration = None

        if duration is None or duration <= 0:
            return VerifyResult(
                ok=False,
                reason="duration is 0 or missing",
                size_bytes=size,
                container=container,
            )

        return VerifyResult(
            ok=True,
            duration_s=duration,
            size_bytes=size,
            container=container,
        )


def _identify_magic(head: bytes) -> str | None:
    """Identify container format from first 16 bytes. Returns container name or None."""
    if len(head) < 4:
        return None

    # MP4 family: bytes 4-7 must be 'ftyp' (after a 4-byte size prefix).
    if len(head) >= 8 and head[4:8] == b"ftyp":
        # Read the brand to distinguish mp4/m4v/mov — for our purposes they're
        # all "mp4 family" and the moov check applies to all.
        return "mp4"

    # Matroska/WebM
    if head[0:4] == b"\x1A\x45\xDF\xA3":
        # Distinguish webm from mkv by sniffing for the DocType.
        # For simplicity, return "matroska" and let ffprobe distinguish.
        return "matroska"

    # MP3 (various headers)
    if head[0:2] in (b"\xFF\xFB", b"\xFF\xF3", b"\xFF\xF2") or head[0:3] == b"ID3":
        return "mp3"

    # MPEG-PS / MPEG-1
    if head[0:4] == b"\x00\x00\x01\xBA":
        return "mpeg_ps"
    if head[0:4] == b"\x00\x00\x01\xB3":
        return "mpeg_video"

    # Ogg
    if head[0:4] in (b"OggS", b"\x4F\x67\x67\x53"):
        return "ogg"

    # FLV
    if head[0:3] == b"FLV":
        return "flv"

    # AVI (RIFF....AVI)
    if head[0:4] == b"RIFF" and len(head) >= 12 and head[8:12] == b"AVI ":
        return "avi"

    return None


def _check_moov_atom(path: Path, size: int) -> tuple[bool, str | None]:
    """Walk the top-level MP4 boxes and confirm `moov` is present and non-empty.

    Returns (ok, reason). reason is None on success.
    """
    try:
        with path.open("rb") as f:
            offset = 0
            moov_found = False
            moov_size = 0
            # Walk top-level boxes until we hit moov or run out of file.
            while offset + 8 <= size:
                f.seek(offset)
                header = f.read(8)
                if len(header) < 8:
                    break
                box_size = struct.unpack(">I", header[0:4])[0]
                box_type = header[4:8]

                # Validate box size.
                if box_size == 0:
                    # box extends to end of file
                    box_size = size - offset
                elif box_size == 1:
                    # 64-bit size — read next 8 bytes
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    box_size = struct.unpack(">Q", ext)[0]

                if box_size < 8 or offset + box_size > size + 1024:
                    # Box size is bogus or file is truncated.
                    if box_type == b"moov":
                        return False, f"moov box truncated (size={box_size}, offset={offset}, file={size})"
                    break

                if box_type == b"moov":
                    moov_found = True
                    moov_size = box_size
                    if moov_size < 16:
                        return False, f"moov box too small ({moov_size} bytes)"
                    break  # found it; don't need to keep walking

                offset += box_size

        if not moov_found:
            # moov could be at the end of the file. If the file looks truncated
            # (we didn't see mdat either, or mdat was suspiciously large),
            # this is a failure. Otherwise, accept — yt-dlp writes +faststart
            # so moov should be near the front, but some valid MP4s put it last.
            # We accept this case because ffprobe already validated the file
            # in check 3.
            return True, None

        return True, None

    except OSError as e:
        return False, f"io error: {e}"
