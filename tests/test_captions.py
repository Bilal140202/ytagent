"""Tests for ytagent.captions — parsing, segmentation, translation, SRT."""

from __future__ import annotations

import re

import pytest

from ytagent import captions
from ytagent.captions import CaptionLine, Cue
from ytagent.innertube import parse_player_response


def test_parse_json3_lines(captions_json3):
    lines = captions.parse_json3_lines(captions_json3)
    # 5 content lines; '\\n' separators and the seg-less event are dropped.
    assert len(lines) == 5
    assert lines[0].start_ms == 1000
    assert lines[0].end_ms == 3000
    assert lines[0].text == "안녕하세요 여러분."
    assert lines[-1].start_ms == 21000


def test_parse_json3_lines_missing_duration_defaults():
    data = {"events": [{"tStartMs": 500, "segs": [{"utf8": "짧은"}]}]}
    (line,) = captions.parse_json3_lines(data)
    assert line.end_ms == 2500  # 2 s default


def test_apply_substitutions_longest_first():
    subs = {"아연": "AHYEON", "아연 씨": "AHYEON"}
    # Longest key first: the honorific form is consumed as one unit.
    assert captions.apply_substitutions("아연 씨가 왔다", subs) == "AHYEON가 왔다"
    assert captions.apply_substitutions("그냥 아연", subs) == "그냥 AHYEON"
    assert captions.apply_substitutions("변경 없음", None) == "변경 없음"


def test_segment_sentence_breaks(captions_json3):
    lines = captions.parse_json3_lines(captions_json3)
    cues = captions.segment_lines(lines, substitutions={"ELLIE": "ELLIE"})
    # Sentence-final '.' closes cues 1 and 2; the split sentence stays joined
    # until its terminal '.'; the 10 s pause before the last line splits it.
    assert len(cues) == 4
    assert cues[0].source == "안녕하세요 여러분."
    assert "ELLIE" in cues[1].source
    assert cues[2].source == "이것은 아주 긴 문장의 앞부분이고 뒷부분입니다."
    assert cues[3].start_ms == 21000


def test_segment_span_cap():
    lines = [CaptionLine(i * 3000, i * 3000 + 2900, f"단어{i} 단어 단어") for i in range(6)]
    cues = captions.segment_lines(lines, max_span_ms=7000, max_chars=10_000)
    assert all(c.end_ms - c.start_ms <= 7000 + 2900 for c in cues)
    assert len(cues) >= 3  # 17.4 s of speech cannot fit in one 7 s cue


def test_segment_char_cap():
    lines = [CaptionLine(i * 1000, i * 1000 + 900, "가" * 30) for i in range(4)]
    cues = captions.segment_lines(lines, max_chars=62, max_span_ms=60_000)
    assert all(len(c.source) <= 62 + 30 for c in cues)
    assert len(cues) >= 2


def _upper_translator(text, sl, tl):
    return text.upper()


def test_translate_cues_batch_and_fallback():
    cues = [Cue(0, 1000, "one"), Cue(1000, 2000, "two"), Cue(2000, 3000, "three")]
    out = captions.translate_cues(cues, "ko", "en", translator=_upper_translator,
                                  batch_size=3, sleep_s=0)
    assert [c.text for c in out] == ["ONE", "TWO", "THREE"]


def test_translate_cues_sentinel_mismatch_falls_back_per_cue():
    def eats_sentinel(text, sl, tl):
        # Simulate a translator that destroys the sentinel when batching.
        if captions.SENTINEL in text:
            return "merged everything"
        return text + "!"

    cues = [Cue(0, 1000, "a"), Cue(1000, 2000, "b")]
    out = captions.translate_cues(cues, "ko", "en", translator=eats_sentinel,
                                  batch_size=2, sleep_s=0)
    assert [c.text for c in out] == ["a!", "b!"]


def test_translate_cues_retries_then_raises():
    def always_fail(text, sl, tl):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        captions.translate_cues([Cue(0, 1, "x")], "ko", "en",
                                translator=always_fail, sleep_s=0, retries=2)


SRT_HEAD = re.compile(r"^\d+\n\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}\n", re.M)


def test_cues_to_srt_format_and_overlap_clamp():
    cues = [
        Cue(0, 5000, "", text="First cue here."),
        Cue(4900, 9000, "", text="Second cue overlaps slightly."),
    ]
    srt = captions.cues_to_srt(cues)
    blocks = srt.strip().split("\n\n")
    assert len(blocks) == 2
    for b in blocks:
        assert SRT_HEAD.match(b + "\n")
    # First cue must end at most 60 ms before the second starts.
    m = re.search(r"--> (\d{2}):(\d{2}):(\d{2}),(\d{3})", blocks[0])
    end_ms = ((int(m[1]) * 60 + int(m[2])) * 60 + int(m[3])) * 1000 + int(m[4])
    assert end_ms <= 4900 - 60 + 1


def test_cues_to_srt_wraps_long_text():
    long_text = " ".join(["word"] * 30)
    srt = captions.cues_to_srt([Cue(0, 6000, "", text=long_text)])
    body = srt.strip().split("\n", 2)[2]
    assert len(body.split("\n")) <= 2


def test_build_subtitles_end_to_end(player_response_ok, captions_json3):
    info = parse_player_response(player_response_ok)

    def fake_fetch(track):
        assert track.language_code == "ko"
        return captions_json3

    def fake_translator(text, sl, tl):
        assert (sl, tl) == ("ko", "en")
        return text.replace("안녕하세요 여러분.", "Hello everyone.")

    result = captions.build_subtitles(
        info,
        target_lang="en",
        substitutions={"ELLIE": "ELLIE"},
        translator=fake_translator,
        fetch_json3=fake_fetch,
    )
    assert result.translated is True
    assert result.source_lang == "ko"
    assert result.cue_count == 4
    assert "Hello everyone." in result.srt
    assert "ELLIE" in result.srt


def test_build_subtitles_same_language_skips_translation(player_response_ok, captions_json3):
    info = parse_player_response(player_response_ok)
    result = captions.build_subtitles(
        info, target_lang="ko", fetch_json3=lambda track: captions_json3
    )
    assert result.translated is False
    assert "안녕하세요" in result.srt


def test_build_subtitles_no_tracks_raise():
    info = parse_player_response({"playabilityStatus": {"status": "OK"}})
    with pytest.raises(ValueError):
        captions.build_subtitles(info)
