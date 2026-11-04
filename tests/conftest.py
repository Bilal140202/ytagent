"""Shared synthetic fixtures — no network, no real video data."""

from __future__ import annotations

import pytest


@pytest.fixture()
def player_response_ok() -> dict:
    """A minimal but realistic Innertube player response (iOS client shape)."""
    return {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {
            "videoId": "VIDEOID1234",
            "title": "Some Radio Broadcast",
            "lengthSeconds": "3690",
        },
        "captions": {
            "playerCaptionsTracklistRenderer": {
                "captionTracks": [
                    {
                        "baseUrl": "https://www.youtube.com/api/timedtext?v=VIDEOID1234&caps=asr",
                        "name": {"simpleText": "Korean (auto-generated)"},
                        "languageCode": "ko",
                        "kind": "asr",
                        "isTranslatable": True,
                    }
                ]
            }
        },
        "streamingData": {
            "expiresInSeconds": "21540",
            "formats": [{"itag": 18, "mimeType": 'video/mp4; codecs="avc1.42001E"', "url": "https://x/y"}],
            "adaptiveFormats": [
                {"itag": 136, "mimeType": 'video/mp4; codecs="avc1.64001F"', "url": "https://x/v"},
                {"itag": 140, "mimeType": 'audio/mp4; codecs="mp4a.40.2"', "url": "https://x/a"},
            ],
        },
    }


@pytest.fixture()
def player_response_login_required() -> dict:
    return {
        "playabilityStatus": {
            "status": "LOGIN_REQUIRED",
            "reason": "Sign in to confirm you're not a bot",
        },
        "videoDetails": {"videoId": "VIDEOID1234"},
    }


@pytest.fixture()
def captions_json3() -> dict:
    """ASR-shaped json3: content lines interleaved with '\\n' separators."""

    def ev(start, dur, text):
        return {"tStartMs": start, "dDurationMs": dur, "segs": [{"utf8": text}]}

    return {
        "wireMagic": "pb3",
        "events": [
            ev(1000, 2000, "안녕하세요 여러분."),
            ev(2900, 100, "\n"),
            ev(3000, 2000, "오늘은 ELLIE 씨와 함께합니다."),
            ev(4900, 100, "\n"),
            ev(5000, 2500, "이것은 아주 긴 문장의 앞부분이고"),
            ev(7400, 100, "\n"),
            ev(7500, 2500, "뒷부분입니다."),
            {"tStartMs": 20000, "dDurationMs": 1000},  # no segs: must be skipped
            ev(21000, 2000, "마지막 인사입니다. 감사합니다."),
        ],
    }
