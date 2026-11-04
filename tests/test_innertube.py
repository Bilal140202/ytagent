"""Tests for ytagent.innertube — parsing (pure) and client rotation."""

from __future__ import annotations

from ytagent import innertube


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_parse_ok_response(player_response_ok):
    info = innertube.parse_player_response(player_response_ok)
    assert info.ok
    assert info.playability_status == "OK"
    assert info.title == "Some Radio Broadcast"
    assert info.length_seconds == 3690
    assert len(info.caption_tracks) == 1
    track = info.caption_tracks[0]
    assert track.language_code == "ko"
    assert track.kind == "asr"
    assert track.is_translatable is True
    assert track.base_url.startswith("https://www.youtube.com/api/timedtext")
    assert len(info.formats) == 1
    assert len(info.adaptive_formats) == 2
    d = info.to_dict()
    assert d["caption_tracks"][0]["language_code"] == "ko"
    assert "raw" not in d


def test_parse_login_required(player_response_login_required):
    info = innertube.parse_player_response(player_response_login_required)
    assert not info.ok
    assert info.playability_status == "LOGIN_REQUIRED"
    assert "bot" in info.playability_reason
    assert info.caption_tracks == []


def test_parse_tolerates_garbage():
    info = innertube.parse_player_response({}, video_id="VIDEOID1234")
    assert info.video_id == "VIDEOID1234"
    assert info.length_seconds == 0
    assert not info.ok


def test_fetch_player_rotates_clients(monkeypatch, player_response_ok, player_response_login_required):
    """First client bot-walled, second OK -> returns OK and names the client."""
    responses = [_FakeResp(player_response_login_required), _FakeResp(player_response_ok)]
    calls = []

    def fake_safe_request(session, method, url, **kwargs):
        calls.append(kwargs["json"]["context"]["client"]["clientName"])
        return responses.pop(0)

    monkeypatch.setattr(innertube, "safe_request", fake_safe_request)
    info = innertube.fetch_player("VIDEOID1234", session=object())
    assert info.ok
    assert calls == ["IOS", "ANDROID_VR"]  # iOS tried first, VR second
    assert info.client_used == "android_vr"


def test_fetch_player_all_fail_returns_last(monkeypatch, player_response_login_required):
    def fake_safe_request(session, method, url, **kwargs):
        return _FakeResp(player_response_login_required)

    monkeypatch.setattr(innertube, "safe_request", fake_safe_request)
    info = innertube.fetch_player("VIDEOID1234", session=object())
    assert not info.ok
    assert info.playability_status == "LOGIN_REQUIRED"
    assert info.client_used == "tvhtml5"  # last client tried


def test_fetch_player_network_errors_never_raise(monkeypatch):
    monkeypatch.setattr(innertube, "safe_request", lambda *a, **k: None)
    info = innertube.fetch_player("VIDEOID1234", session=object())
    assert info.playability_status == "NO_RESPONSE"
