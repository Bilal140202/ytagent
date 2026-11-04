"""Caption salvage + subtitle building.

The pipeline that produced a publishable English SRT from a datacenter IP
(field report: docs/subtitles-and-datacenter-playbook.md):

1. ``fetch_caption_json3`` — GET the caption track's signed ``baseUrl`` with
   ``&fmt=json3``. The *source-language* track fetches reliably; do **not**
   rely on YouTube's ``&tlang=`` translation of it — from datacenter IPs
   tlang is rate-limited (HTTP 429) while the source track succeeds.
2. ``parse_json3_lines`` — json3 events -> timed lines (word-level timing
   lives in the segments; line starts/ends are what SRT cues need).
3. ``segment_lines`` — group lines into readable cues: break on sentence
   punctuation, on pauses, and at hard caps (default 7 s / 62 chars).
   Optional proper-noun ``substitutions`` are applied to the source text
   *before* translation so a translator can never mangle names — including
   names the ASR itself misheard (the report documents a real case).
4. ``translate_cues`` — translate cue-by-cue in sentinel-joined batches
   (default translator: the Google Translate web endpoint, ``gtx``). The
   translator callable is injectable for tests and for swapping providers.
5. ``cues_to_srt`` — render standard SRT (<=42-char wrapped lines, no
   overlapping cues).

Everything except the two fetch functions is pure and unit-tested.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .innertube import CaptionTrack
from .utils.net import DEFAULT_UA

SENTINEL = "ZXQMARKERZXQ"
GTX_URL = "https://translate.googleapis.com/translate_a/single"


@dataclass
class CaptionLine:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    source: str
    text: str = ""  # translated text; falls back to source when untranslated

    def display(self) -> str:
        return self.text or self.source


# --------------------------------------------------------------------------
# Fetching (network)
# --------------------------------------------------------------------------

def fetch_caption_json3(track: CaptionTrack, *, timeout: int = 30) -> dict[str, Any]:
    """Fetch a caption track as json3. Raises on HTTP/network errors."""
    if not track.base_url:
        raise ValueError("caption track has no baseUrl")
    url = track.base_url + "&fmt=json3"
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def gtx_translate(text: str, source_lang: str, target_lang: str, *, timeout: int = 40) -> str:
    """Translate one string via the Google Translate web endpoint (gtx).

    No API key. Raises on failure so callers can retry/fall back.
    """
    q = urllib.parse.quote(text)
    url = f"{GTX_URL}?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q={q}"
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode("utf-8"))
    return "".join(seg[0] for seg in out[0] if seg and seg[0])


# --------------------------------------------------------------------------
# Parsing + segmentation (pure)
# --------------------------------------------------------------------------

def parse_json3_lines(data: dict[str, Any]) -> list[CaptionLine]:
    """Convert YouTube json3 caption data to timed lines.

    Events whose entire text is ``\\n`` are window separators in ASR tracks
    and are dropped. Events missing ``dDurationMs`` get a 2 s default.
    """
    lines: list[CaptionLine] = []
    for e in data.get("events", []):
        segs = e.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text or text == "\\n":
            continue
        start = int(e.get("tStartMs") or 0)
        dur = int(e.get("dDurationMs") or 2000)
        lines.append(CaptionLine(start_ms=start, end_ms=start + dur, text=text))
    return lines


def apply_substitutions(text: str, substitutions: dict[str, str] | None) -> str:
    """Replace source-language names/terms with their canonical forms.

    Order matters: longer keys are applied first so e.g. a full name wins
    over a shorter substring it contains.
    """
    if not substitutions:
        return text
    for key in sorted(substitutions, key=len, reverse=True):
        text = text.replace(key, substitutions[key])
    return text


def segment_lines(
    lines: Iterable[CaptionLine],
    *,
    substitutions: dict[str, str] | None = None,
    max_span_ms: int = 7000,
    max_chars: int = 62,
    pause_ms: int = 2500,
) -> list[Cue]:
    """Group timed lines into subtitle cues.

    A cue closes when the next line would (a) start after a pause longer
    than ``pause_ms``, (b) push the cue span past ``max_span_ms``, or
    (c) push the joined text past ``max_chars`` — or immediately when the
    accumulated text ends with sentence-final punctuation.
    """
    cues: list[Cue] = []
    cur: Cue | None = None

    for line in lines:
        text = apply_substitutions(line.text, substitutions)
        if cur is None:
            cur = Cue(start_ms=line.start_ms, end_ms=line.end_ms, source=text)
        else:
            gap = line.start_ms - cur.end_ms
            span = line.end_ms - cur.start_ms
            if gap > pause_ms or span > max_span_ms or len(cur.source) + len(text) > max_chars:
                cues.append(cur)
                cur = Cue(start_ms=line.start_ms, end_ms=line.end_ms, source=text)
            else:
                cur.end_ms = line.end_ms
                cur.source += " " + text
        if cur.source.rstrip().endswith((".", "?", "!", "…", '"')) and len(cur.source) >= 8:
            cues.append(cur)
            cur = None
    if cur is not None:
        cues.append(cur)
    return cues


# --------------------------------------------------------------------------
# Translation (batching pure-ish; translator injectable)
# --------------------------------------------------------------------------

Translator = Callable[[str, str, str], str]


def translate_cues(
    cues: list[Cue],
    source_lang: str,
    target_lang: str,
    *,
    translator: Translator = gtx_translate,
    batch_size: int = 10,
    sleep_s: float = 0.4,
    retries: int = 3,
) -> list[Cue]:
    """Translate cues in sentinel-joined batches; per-cue fallback.

    Batches join cue texts with a sentinel token that survives machine
    translation, then split the result back apart. If a batch's part count
    doesn't match its cue count (sentinel mangled), each cue in that batch
    is translated individually. Cues whose source already equals the target
    language are left untouched by the caller, not here.
    """

    def _one(text: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                return translator(text, source_lang, target_lang)
            except Exception as exc:  # translator is external; retry broadly
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"translation failed after {retries} tries: {last_exc}")

    for i in range(0, len(cues), batch_size):
        batch = cues[i : i + batch_size]
        if len(batch) == 1:
            batch[0].text = _one(batch[0].source).strip()
        else:
            joined = ("\n" + SENTINEL + "\n").join(c.source for c in batch)
            out = _one(joined)
            parts = [re.sub(r"\s*\n\s*", " ", p).strip() for p in out.split(SENTINEL)]
            if len(parts) != len(batch):
                parts = [_one(c.source).strip() for c in batch]
            for cue, part in zip(batch, parts, strict=True):
                cue.text = part
        if sleep_s:
            time.sleep(sleep_s)
    return cues


# --------------------------------------------------------------------------
# SRT rendering (pure)
# --------------------------------------------------------------------------

def _ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def wrap_text(text: str, width: int = 42) -> list[str]:
    """Wrap to at most 2 lines of <=width chars where possible."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 <= width:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) <= 2:
        return lines
    # Rebalance into 2 lines near the midpoint.
    best: tuple[str, str] | None = None
    best_diff = 10**9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if abs(len(a) - len(b)) < best_diff and len(a) <= width + 8 and len(b) <= width + 8:
            best_diff = abs(len(a) - len(b))
            best = (a, b)
    if best:
        return [best[0], best[1]]
    return [" ".join(lines[:2]), " ".join(lines[2:])]


def cues_to_srt(cues: list[Cue]) -> str:
    """Render cues as an SRT document. Guarantees non-overlapping cues."""
    out: list[str] = []
    ordered = sorted(cues, key=lambda c: c.start_ms)
    for i, cue in enumerate(ordered):
        end = cue.end_ms
        if i + 1 < len(ordered):
            nxt = ordered[i + 1].start_ms
            if end > nxt - 60:
                end = max(cue.start_ms + 400, nxt - 60)
        body = "\n".join(wrap_text(re.sub(r"\s+", " ", cue.display()).strip()))
        out.append(f"{i + 1}\n{_ts(cue.start_ms)} --> {_ts(end)}\n{body}\n")
    return "\n".join(out)


# --------------------------------------------------------------------------
# End-to-end helper
# --------------------------------------------------------------------------

@dataclass
class SubtitleResult:
    video_id: str
    title: str
    source_lang: str
    target_lang: str
    cue_count: int
    srt: str
    translated: bool
    caption_kind: str = ""
    notes: list[str] = field(default_factory=list)


def build_subtitles(
    info: Any,
    *,
    target_lang: str = "en",
    source_lang: str | None = None,
    substitutions: dict[str, str] | None = None,
    translator: Translator = gtx_translate,
    fetch_json3: Callable[[CaptionTrack], dict[str, Any]] = fetch_caption_json3,
) -> SubtitleResult:
    """Build an SRT from a PlayerInfo (see innertube.fetch_player).

    Picks the requested source track (or the first track), segments it,
    and translates when ``target_lang`` differs from the source language.
    """
    if not info.caption_tracks:
        raise ValueError("player response has no caption tracks")
    track = None
    if source_lang:
        track = next((t for t in info.caption_tracks if t.language_code == source_lang), None)
    track = track or info.caption_tracks[0]

    data = fetch_json3(track)
    lines = parse_json3_lines(data)
    cues = segment_lines(lines, substitutions=substitutions)

    translated = target_lang != track.language_code
    notes: list[str] = []
    if translated:
        translate_cues(cues, track.language_code, target_lang, translator=translator)
    else:
        notes.append("target == source language; no translation performed")

    return SubtitleResult(
        video_id=info.video_id,
        title=info.title,
        source_lang=track.language_code,
        target_lang=target_lang,
        cue_count=len(cues),
        srt=cues_to_srt(cues),
        translated=translated,
        caption_kind=track.kind,
        notes=notes,
    )
