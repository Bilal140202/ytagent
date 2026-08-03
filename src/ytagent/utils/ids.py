"""YouTube URL / video-ID parsing.

to_video_id(target) accepts any of:
  - https://www.youtube.com/watch?v=ID
  - https://youtu.be/ID
  - https://www.youtube.com/embed/ID
  - https://www.youtube.com/shorts/ID
  - https://www.youtube.com/v/ID
  - https://m.youtube.com/watch?v=ID
  - https://music.youtube.com/watch?v=ID
  - bare 11-char ID
  - URL with extra query params (&list=, &t=, &feature=, etc.)

Returns the 11-char ID or raises ValueError.

Never makes a network call. Pure regex/parse.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

# YouTube video IDs are exactly 11 chars from [A-Za-z0-9_-].
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Find an 11-char ID in a path segment after known YouTube path prefixes.
_PATH_ID_PATTERNS = [
    re.compile(r"/embed/(?P<id>[A-Za-z0-9_-]{11})"),
    re.compile(r"/shorts/(?P<id>[A-Za-z0-9_-]{11})"),
    re.compile(r"/v/(?P<id>[A-Za-z0-9_-]{11})"),
    re.compile(r"/live/(?P<id>[A-Za-z0-9_-]{11})"),
]


def is_video_id(s: str) -> bool:
    """Return True if `s` is exactly an 11-char YouTube video ID."""
    return bool(_VIDEO_ID_RE.match(s))


def parse_youtube_url(url: str) -> str | None:
    """Parse a YouTube URL and return the video ID, or None if not parseable."""
    if not url or not isinstance(url, str):
        return None

    url = url.strip()

    # Bare ID shortcut.
    if is_video_id(url):
        return url

    # Add scheme if missing so urlparse works.
    if url.startswith("//"):
        url = "https:" + url
    elif "://" not in url and url.startswith("/"):
        url = "https://youtube.com" + url
    elif "://" not in url:
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")

    # Standard watch URL.
    if host.endswith("youtube.com") or host.endswith("youtu.be") or host.endswith("youtube-nocookie.com"):
        # youtu.be/<ID>
        if host == "youtu.be":
            m = _VIDEO_ID_RE.match(path.strip("/"))
            if m:
                return m.group(0)
            # Sometimes /youtu.be/<ID>?si=...
            seg = path.strip("/").split("/")[0] if path.strip("/") else ""
            if is_video_id(seg):
                return seg

        # watch?v=ID
        v = query.get("v", [None])[0]
        if v and is_video_id(v):
            return v

        # ?vi=ID (older share format)
        vi = query.get("vi", [None])[0]
        if vi and is_video_id(vi):
            return vi

        # /embed/ID, /shorts/ID, /v/ID, /live/ID
        for pat in _PATH_ID_PATTERNS:
            m = pat.search(path)
            if m:
                return m.group("id")

    return None


def to_video_id(target: str) -> str:
    """Parse any YouTube URL shape or bare ID into a canonical 11-char ID.

    Raises ValueError if the input matches no known shape.
    Never makes a network call.
    """
    if not target or not isinstance(target, str):
        raise ValueError(f"to_video_id: empty or non-string input: {target!r}")

    target = target.strip()

    if is_video_id(target):
        return target

    vid = parse_youtube_url(target)
    if vid:
        return vid

    raise ValueError(
        f"to_video_id: could not extract video ID from {target!r}. "
        f"Expected a YouTube URL or 11-char ID."
    )
