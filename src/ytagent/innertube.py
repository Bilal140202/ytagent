"""Shared Innertube player access — metadata + caption tracks.

Why this module exists (field report, 2026-11-04, docs/subtitles-and-datacenter-playbook.md):
from a datacenter IP, yt-dlp and the ANDROID_VR client were bot-walled
(``LOGIN_REQUIRED``) for a public video, while a raw player POST with the
**iOS** client context returned ``playabilityStatus: OK`` with full metadata,
caption tracks and streaming data. Even when the media bytes themselves
cannot be fetched (signed googlevideo URLs are egress-IP-bound across their
302 redirect), the metadata + captions are a useful partial success — for
subtitle tasks they *are* the deliverable.

This module is deliberately small and dependency-light:

- ``CLIENTS`` — client contexts in the order they should be tried.
- ``parse_player_response`` — pure function, dict -> PlayerInfo (unit-tested).
- ``fetch_player`` — network wrapper; tries clients in order, returns the
  first response whose playability is OK / LIVE_STREAM_OFFLINE, or the last
  response seen. Never raises.

It does **not** download media. See ``methods/innertube_direct.py`` for the
download method, and ``captions.py`` for what to do with the caption tracks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .utils.net import DEFAULT_UA, make_session, safe_request

# Public Innertube API key (the standard WEB client key; it ships in every
# YouTube web page and in yt-dlp's source). Not a credential.
INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
PLAYER_URL = "https://www.youtube.com/youtubei/v1/player"

# Client contexts, best-first for datacenter/cloud use as of 2026-11.
# iOS first: it answered OK where ANDROID_VR returned LOGIN_REQUIRED.
# ANDROID_VR kept second (JS-less, works on many networks), TVHTML5 third.
CLIENTS: list[dict[str, Any]] = [
    {
        "name": "ios",
        "client": {
            "clientName": "IOS",
            "clientVersion": "20.10.4",
            "deviceMake": "Apple",
            "deviceModel": "iPhone16,2",
            "osName": "iPhone",
            "osVersion": "18.3.2.22D82",
        },
        "user_agent": "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)",
    },
    {
        "name": "android_vr",
        "client": {
            "clientName": "ANDROID_VR",
            "clientVersion": "1.65.10",
            "deviceMake": "Oculus",
            "deviceModel": "Quest 3",
            "androidSdkVersion": 32,
            "osName": "Android",
            "osVersion": "12L",
        },
        "user_agent": DEFAULT_UA,
    },
    {
        "name": "tvhtml5",
        "client": {
            "clientName": "TVHTML5",
            "clientVersion": "7.20241201.14.00",
        },
        "user_agent": DEFAULT_UA,
    },
]


@dataclass
class CaptionTrack:
    """One caption track from playerCaptionsTracklistRenderer."""

    language_code: str
    kind: str = ""  # "asr" for automatic captions, "" for manual
    name: str = ""
    base_url: str = ""
    is_translatable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "language_code": self.language_code,
            "kind": self.kind,
            "name": self.name,
            "base_url": self.base_url,
            "is_translatable": self.is_translatable,
        }


@dataclass
class PlayerInfo:
    """The useful slice of an Innertube player response."""

    video_id: str
    playability_status: str = ""
    playability_reason: str = ""
    title: str = ""
    length_seconds: int = 0
    client_used: str = ""
    caption_tracks: list[CaptionTrack] = field(default_factory=list)
    formats: list[dict[str, Any]] = field(default_factory=list)
    adaptive_formats: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return self.playability_status in ("OK", "LIVE_STREAM_OFFLINE")

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly summary (excludes the raw response)."""
        return {
            "video_id": self.video_id,
            "playability_status": self.playability_status,
            "playability_reason": self.playability_reason,
            "title": self.title,
            "length_seconds": self.length_seconds,
            "client_used": self.client_used,
            "caption_tracks": [t.to_dict() for t in self.caption_tracks],
            "format_count": len(self.formats),
            "adaptive_format_count": len(self.adaptive_formats),
        }


def parse_player_response(data: dict[str, Any], video_id: str = "") -> PlayerInfo:
    """Parse an Innertube player response dict into a PlayerInfo. Pure."""
    playability = data.get("playabilityStatus", {}) or {}
    details = data.get("videoDetails", {}) or {}
    streaming = data.get("streamingData", {}) or {}

    tracks: list[CaptionTrack] = []
    renderer = (
        data.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks", [])
    ) or []
    for t in renderer:
        name = t.get("name", {})
        tracks.append(
            CaptionTrack(
                language_code=t.get("languageCode", ""),
                kind=t.get("kind", ""),
                name=name.get("simpleText", "") if isinstance(name, dict) else "",
                base_url=t.get("baseUrl", ""),
                is_translatable=bool(t.get("isTranslatable", False)),
            )
        )

    try:
        length = int(details.get("lengthSeconds") or 0)
    except (TypeError, ValueError):
        length = 0

    return PlayerInfo(
        video_id=details.get("videoId") or video_id,
        playability_status=playability.get("status", ""),
        playability_reason=playability.get("reason", "") or "",
        title=details.get("title", "") or "",
        length_seconds=length,
        caption_tracks=tracks,
        formats=streaming.get("formats", []) or [],
        adaptive_formats=streaming.get("adaptiveFormats", []) or [],
        raw=data,
    )


def fetch_player(
    video_id: str,
    *,
    session: Any = None,
    clients: list[dict[str, Any]] | None = None,
    timeout: int = 20,
) -> PlayerInfo:
    """Fetch the player response, trying clients in order. Never raises.

    Returns the first OK response; if no client returns OK, returns the
    last parsed response (so callers can inspect the failure status).
    """
    session = session or make_session(retries=2, backoff=2.0)
    last: PlayerInfo | None = None

    for cfg in clients or CLIENTS:
        payload = {
            "context": {"client": cfg["client"]},
            "videoId": video_id,
            "racyCheckOk": True,
            "contentCheckOk": True,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": cfg.get("user_agent", DEFAULT_UA),
        }
        resp = safe_request(
            session,
            "POST",
            f"{PLAYER_URL}?key={INNERTUBE_API_KEY}&prettyPrint=false",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        if resp is None or resp.status_code != 200:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        info = parse_player_response(data, video_id=video_id)
        info.client_used = cfg["name"]
        last = info
        if info.ok:
            return info

    return last or PlayerInfo(video_id=video_id, playability_status="NO_RESPONSE")
