"""Tests for the `subtitles` CLI command and the Actions farm token fallback."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ytagent import captions as captions_mod
from ytagent import cli as cli_mod
from ytagent import innertube as innertube_mod
from ytagent.methods import github_actions_farm


def _fake_info():
    return innertube_mod.parse_player_response(
        {
            "playabilityStatus": {"status": "OK"},
            "videoDetails": {"videoId": "VIDEOID1234", "title": "T", "lengthSeconds": "60"},
            "captions": {
                "playerCaptionsTracklistRenderer": {
                    "captionTracks": [
                        {"languageCode": "ko", "kind": "asr", "baseUrl": "https://x", "isTranslatable": True}
                    ]
                }
            },
        }
    )


def test_cli_subtitles_writes_srt(monkeypatch, tmp_path):
    monkeypatch.setattr(innertube_mod, "fetch_player", lambda vid, **k: _fake_info())

    def fake_build(info, **kwargs):
        return captions_mod.SubtitleResult(
            video_id="VIDEOID1234", title="T", source_lang="ko", target_lang="en",
            cue_count=1, srt="1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
            translated=True, caption_kind="asr",
        )

    monkeypatch.setattr(captions_mod, "build_subtitles", fake_build)
    out = tmp_path / "out.srt"
    result = CliRunner().invoke(
        cli_mod.cli, ["subtitles", "VIDEOID1234", "--to", "en", "--out", str(out), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").startswith("1\n00:00:00,000")
    summary = json.loads(result.output)
    assert summary["cues"] == 1
    assert summary["path"] == str(out)


def test_cli_subtitles_unplayable_exits_1(monkeypatch):
    bad = innertube_mod.parse_player_response(
        {"playabilityStatus": {"status": "LOGIN_REQUIRED", "reason": "bot wall"}}
    )
    monkeypatch.setattr(innertube_mod, "fetch_player", lambda vid, **k: bad)
    result = CliRunner().invoke(cli_mod.cli, ["subtitles", "VIDEOID1234"])
    assert result.exit_code == 1
    assert "LOGIN_REQUIRED" in result.output


def test_cli_subtitles_bad_target_exits_2():
    result = CliRunner().invoke(cli_mod.cli, ["subtitles", "not a url at all!!!"])
    assert result.exit_code == 2


def test_farm_uses_env_token(monkeypatch, tmp_path):
    seen = {}

    def fake_trigger(session, token, owner, repo, workflow, video_url):
        seen["token"] = token
        return None  # force the "failed to trigger" path

    monkeypatch.setenv("YTAGENT_GITHUB_TOKEN", "env-token-for-test")
    monkeypatch.setattr(github_actions_farm, "_trigger_workflow", fake_trigger)
    result = github_actions_farm.download("VIDEOID1234", Path(tmp_path))
    assert seen["token"] == "env-token-for-test"
    assert "failed to trigger" in (result.reason or "")


def test_farm_opts_token_wins_over_env(monkeypatch, tmp_path):
    seen = {}

    def fake_trigger(session, token, owner, repo, workflow, video_url):
        seen["token"] = token
        return None

    monkeypatch.setenv("YTAGENT_GITHUB_TOKEN", "env-token-for-test")
    monkeypatch.setattr(github_actions_farm, "_trigger_workflow", fake_trigger)
    github_actions_farm.download("VIDEOID1234", Path(tmp_path), {"github_token": "opts-token"})
    assert seen["token"] == "opts-token"


def test_farm_no_token_reason_mentions_env(monkeypatch, tmp_path):
    monkeypatch.delenv("YTAGENT_GITHUB_TOKEN", raising=False)
    result = github_actions_farm.download("VIDEOID1234", Path(tmp_path))
    assert not result.ok
    assert "YTAGENT_GITHUB_TOKEN" in (result.reason or "")
