# agents.md — Perfection-Based Role Prompts for the `ytagent` Agent Roster

> This file defines each agent in the system as a **role prompt**: a tight, opinionated, mandatory specification of what the agent is, what it does, what it must never do, and the exact interface it exposes. Every implementation file in `src/ytagent/agents/` and `src/ytagent/orchestrator.py` must conform to the prompt for its role.
>
> Read your role. Implement to your role. Test against your role. Deviate and the system fails.

---

## How to use this file

1. Each agent section below is a **self-contained prompt**. If you were to give an LLM (or a human engineer) exactly one section and nothing else, they should be able to implement that agent correctly.
2. The prompts are **imperative and unconditional**. There is no "you may want to" — there is only "you will".
3. The interface signatures (`def`, `Args:`, `Returns:`) are the contract. Changing a signature is a breaking change requiring a `phases.md` amendment.
4. The "Forbidden" lists are exhaustive. Adding to a Forbidden list is allowed; removing from it requires written justification in the PR.

---

## Agent 1 — The Orchestrator

**File:** `src/ytagent/orchestrator.py`
**Class:** `Orchestrator`
**One-line role:** *Receive a YouTube URL or video ID, return a verified file path on disk, or a structured final error.*

### You are the Orchestrator. You will:

- Accept a `target` (URL or 11-char video ID), an `out_dir`, and an `opts` dict.
- Resolve `target` to a canonical 11-character video ID via `utils.ids.to_video_id`.
- Ask the **Truth Agent** for the ordered list of methods to try.
- Walk that list in order. For each method:
  1. Create a fresh temp dir: `out_dir/.tmp/<video_id>/<method_name>/`.
  2. Call `method.download(video_id, temp_dir, opts)` with a per-method timeout.
  3. If the method returns `MethodResult(ok=False)`, log the reason, append an observation, and continue to the next method.
  4. If the method returns `MethodResult(ok=True, path=...)`, hand the path to the **Verifier**.
  5. If the Verifier returns `VerifyResult(ok=True)`, atomically move the file to `out_dir/<video_id>.<ext>` via `os.replace`. Append a success observation. Return the final path.
  6. If the Verifier returns `VerifyResult(ok=False)`, log the reason, append a failure observation, delete the temp file, and continue to the next method.
- If every method is exhausted without a verified success, return a `DownloadResult(ok=False, attempts=[...])` listing every method tried, its `reason`, and the Verifier's reason if applicable.

### Your interface (the contract)

```python
@dataclass
class DownloadResult:
    ok: bool
    video_id: str
    final_path: str | None
    method_used: str | None
    attempts: list[Attempt]              # one per method tried
    total_duration_ms: int

@dataclass
class Attempt:
    method: str
    started_at: str                      # ISO8601 UTC
    finished_at: str
    ok: bool
    reason: str | None                   # method's own reason
    verify_reason: str | None            # Verifier's reason, if method succeeded but verify failed
    bytes_downloaded: int
    duration_ms: int

class Orchestrator:
    def __init__(self, truth: TruthAgent, verifier: Verifier, methods: dict[str, Method]): ...
    def download(self, target: str, out_dir: Path, opts: dict | None = None) -> DownloadResult: ...
```

### You are forbidden from:

- Asking the user any question. The CLI is non-interactive.
- Skipping the Verifier. A path returned by a method is a *claim*, not a fact.
- Reusing a temp path between methods. Each method gets a clean slate.
- Stopping at the first method failure. You walk the entire chain.
- Calling an LLM. You are a deterministic state machine.
- Modifying `state/truth.json` directly. That is the Truth Agent's job. You only *read* the ranking from Truth and *append* observations.
- Writing files outside `out_dir` or its `.tmp/` subdirectory.
- Sleeping more than the configured per-method timeout. Timeouts are hard.

### Your success criteria

- Given a reachable public video, return a verified file path within the sum of method timeouts.
- Given an unreachable video (private, deleted, IP-banned), return a `DownloadResult` with `ok=False` and a complete `attempts` list explaining every method that was tried and why each failed.
- The same input always produces structurally equivalent output (modulo network nondeterminism).
- The `attempts` list is exhaustive and auditable — a downstream agent reading it can reconstruct exactly what happened.

---

## Agent 2 — The Truth Agent

**File:** `src/ytagent/agents/truth.py`
**Class:** `TruthAgent`
**One-line role:** *Know which download methods have historically worked in this environment, and rank them.*

### You are the Truth Agent. You will:

- Own `state/truth.json` (the ranked method list) and `state/observations.jsonl` (the append-only audit log).
- On construction, load `truth.json` into memory. If the file does not exist, write a sane default (the static baseline chain from `CLAUDE.md` §4).
- Expose `ranked_methods() -> list[str]` returning method names in the order they should be tried.
- Expose `record_observation(obs: Observation)` which appends to `observations.jsonl` and, if the observation is a failure, increments that method's `consecutive_failures` counter. If `consecutive_failures >= 3`, demote the method by `rank += 1` (capped at the bottom) and reset the counter. A success resets the counter and may promote the method by `rank -= 1` (floored at 0).
- Atomic writes: never leave `truth.json` in a corrupted state. Write to a temp file then `os.replace`.
- Never lose an observation. Append-only. `observations.jsonl` may grow unbounded; that is acceptable for now. A future phase may add rotation.

### Your interface (the contract)

```python
@dataclass
class Observation:
    ts: str                  # ISO8601 UTC
    video_id: str
    method: str
    ok: bool
    reason: str | None
    bytes: int
    duration_ms: int

class TruthAgent:
    def __init__(self, state_dir: Path): ...
    def ranked_methods(self) -> list[str]: ...
    def record_observation(self, obs: Observation) -> None: ...
    def snapshot(self) -> dict: ...     # for `ytagent truth show`
    def reset(self, method: str | None = None) -> None: ...   # for `ytagent truth reset`
```

### `truth.json` schema

```json
{
  "version": 1,
  "updated_at": "2026-07-30T12:00:00Z",
  "methods": [
    {"name": "transcript_probe",    "rank": 0, "consecutive_failures": 0, "success_ratio": 1.0, "attempts": 0},
    {"name": "ytdlp_default",       "rank": 1, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0},
    {"name": "ytdlp_jsless",        "rank": 2, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0},
    {"name": "ytdlp_ios",           "rank": 3, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0},
    {"name": "ytdlp_single_file",   "rank": 4, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0},
    {"name": "ytdlp_audio_only",    "rank": 5, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0},
    {"name": "innertube_direct",    "rank": 6, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0},
    {"name": "cobalt",              "rank": 7, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0},
    {"name": "piped",               "rank": 8, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0},
    {"name": "invidious",           "rank": 9, "consecutive_failures": 0, "success_ratio": 0.0, "attempts": 0}
  ]
}
```

### You are forbidden from:

- Reading `observations.jsonl` on every call. It is for audit and offline analysis, not for live ranking. Use the in-memory counters in `truth.json`.
- Demoting a method below rank 9. There is no rank 10.
- Promoting a method above rank 0.
- Deleting observations. Append-only means append-only.
- Recommending a method that is not registered in `methods/__init__.py`. Skip unknown methods and log a warning.
- Trusting the static ranking forever. Observed data always wins.

### Your success criteria

- After 3 consecutive failures of `ytdlp_default`, the next `ranked_methods()` call returns it after `ytdlp_jsless` (or lower).
- After a single success of a demoted method, its `consecutive_failures` resets to 0 but its rank does not immediately recover — it requires sustained success.
- The file is never corrupted even if the process is killed mid-write.

---

## Agent 3 — The Verifier

**File:** `src/ytagent/agents/verifier.py`
**Class:** `Verifier`
**One-line role:** *Given a file path, confirm it is a real, playable, non-truncated video. Return a structured verdict.*

### You are the Verifier. You will run these 6 checks in order, fail-fast:

1. **Existence & size.** The path exists, is a regular file, and `st_size >= 1_000_000` bytes (1 MB). Anything smaller is almost certainly an error page or a truncated header.
2. **Magic bytes.** The first 12 bytes match a known video container signature:
   - `00 00 00 XX 66 74 79 70` — MP4/M4V/MOV (`ftyp` box)
   - `1A 45 DF A3` — Matroska/WebM (EBML)
   - `FF FB` / `FF F3` / `FF F2` / `49 44 33` — MP3 (for audio-only fallback)
   - `00 00 01 BA` / `00 00 01 B3` — MPEG-PS / MPEG-1
   - `OggS` — Ogg
   - If the file starts with `<!DOCTYPE` or `<html`, fail immediately with `reason="file is HTML, not video"`.
3. **ffprobe probe.** Run `ffprobe -v error -show_format -show_streams -print_format json <path>`. Exit code 0 required. Parse the JSON.
4. **Duration.** `format.duration` (or the longest stream duration) must be `> 0`. A 0-second file is a stub or an error.
5. **At least one video or audio stream.** `streams` must contain at least one entry with `codec_type` in `{"video", "audio"}`. (Audio-only fallbacks are allowed; the Orchestrator explicitly tries them in Tier 4.)
6. **moov atom sanity (MP4 only).** For MP4/M4V/MOV files, walk the top-level boxes and confirm `moov` is present and non-empty. If `moov` is at the end of the file (no `+faststart`) AND the file's reported duration exceeds what's actually decodable, that's a truncation signal — fail with `reason="moov atom indicates truncation"`.

### Your interface (the contract)

```python
@dataclass
class VerifyResult:
    ok: bool
    reason: str | None
    duration_s: float | None
    size_bytes: int | None
    container: str | None             # "mp4", "webm", "matroska", "mp3", etc.
    video_codec: str | None
    audio_codec: str | None

class Verifier:
    def __init__(self, ffprobe_path: str = "ffprobe"): ...
    def verify(self, path: Path) -> VerifyResult: ...
    def verify_quick(self, path: Path) -> VerifyResult: ...   # checks 1-4 only, for in-progress polling
```

### You are forbidden from:

- Trusting the file extension. Verify by content.
- Running `ffplay` or any GUI tool. Headless only.
- Mutating the file. Read-only.
- Taking more than 10 seconds. `ffprobe` is fast; if it hangs, kill it and fail.
- Passing a verdict without running all 6 checks (unless an earlier check fails, in which case fail-fast is correct).
- Considering a 0-byte file as "audio-only". A 0-byte file is always a failure.

### Your success criteria

- A real 5-second MP4 passes all 6 checks.
- A truncated MP4 (head + half the body, no moov) fails check 6.
- An HTML error page saved as `.mp4` fails check 2.
- A 500-byte stub fails check 1.
- A valid WebM passes checks 1-5 (check 6 is MP4-only and skipped).
- The whole verdict completes in < 2 seconds for a 50 MB file.

---

## Agent 4 — The Tester

**File:** `src/ytagent/agents/tester.py`
**Class:** `Tester`
**One-line role:** *Prove the system works end-to-end against known-stable public videos. Exit 0 on success, non-zero on failure.*

### You are the Tester. You will:

- Maintain a corpus of known-stable, Creative-Commons or public-domain YouTube videos in `tests/corpus.py`. The default corpus consists of 5 widely-embedded, stable public videos suitable for smoke testing. The specific video IDs are defined in `tests/corpus.py` and may be updated as needed.
- Run in two modes:
  - **`--quick`** (default): run only the first corpus video through the full pipeline. Must complete in < 120 seconds. Used for `ytagent --self-test` and pre-commit.
  - **`--full`**: run all 5 corpus videos sequentially, with a 5-second sleep between each to avoid rate-limiting. Used for nightly CI.
- For each video: call `Orchestrator.download`, assert `result.ok is True`, assert the file passes `Verifier.verify`, then delete the file (we're testing the pipeline, not hoarding videos).
- Print a summary table: video ID × method used × duration × size × verdict.
- Exit 0 if all videos passed, non-zero otherwise.
- Write a markdown report to `state/self-test-<timestamp>.md`.

### Your interface (the contract)

```python
@dataclass
class TestReport:
    started_at: str
    finished_at: str
    mode: str                         # "quick" or "full"
    results: list[TestResult]
    exit_code: int

@dataclass
class TestResult:
    video_id: str
    ok: bool
    method_used: str | None
    duration_s: float | None
    size_bytes: int | None
    reason: str | None

class Tester:
    def __init__(self, orchestrator: Orchestrator, verifier: Verifier): ...
    def run(self, mode: str = "quick") -> TestReport: ...
```

### You are forbidden from:

- Downloading the same video twice in one run. Cache results in-memory.
- Hammering YouTube. The 5-second sleep in `--full` mode is mandatory.
- Testing against private or age-restricted videos. The corpus is public-only.
- Treating a network error as a test failure. Distinguish "system broken" from "YouTube unreachable" — the latter should produce a warning, not a hard fail, in `--quick` mode.
- Running without the Verifier. Every downloaded file must be verified.

### Your success criteria

- `ytagent --self-test --quick` exits 0 on a healthy system.
- `ytagent --self-test --full` produces a markdown report with 5 rows.
- A regression in any method is visible in the report's "method used" column — if Tier 1 starts failing, the report shows Tier 2 being used.

---

## Cross-agent contracts (read all of these)

1. **Orchestrator ↔ Truth**: Orchestrator calls `truth.ranked_methods()` once per `download()` call. Orchestrator calls `truth.record_observation(obs)` after every method attempt. No other communication.

2. **Orchestrator ↔ Verifier**: Orchestrator calls `verifier.verify(path)` only after a method reports `ok=True`. The Verifier never sees a method's name or its reason — it only sees the file. This keeps the Verifier unbiased.

3. **Orchestrator ↔ Methods**: Orchestrator calls `method.download(video_id, out_dir, opts)`. The method returns a `MethodResult` and never raises (it catches its own exceptions and returns `ok=False`). If a method *does* raise, the Orchestrator catches it, logs it as a method failure with `reason="method raised: <ExceptionType>: <msg>"`, and continues.

4. **Tester ↔ Orchestrator**: Tester calls `Orchestrator.download` exactly as a real caller would. No special test hooks. If the Tester needs to inject mocks, it does so by constructing an Orchestrator with a mocked `methods` dict.

5. **All agents ↔ Logger**: Every agent logs through `log.py`'s structured logger. The log format is JSONL to stderr plus a rich-formatted summary to stdout. The `trace_id` field ties all log lines for a single `download()` call together.

---

## The perfection bar

These prompts are not aspirational. They are the **minimum**. If an implementation file does not meet every bullet in its role prompt, it is a bug. Code review against this file is mandatory before merge.

When in doubt, ask: *would a downstream AI agent, reading only this `agents.md` and the source file, be able to predict the behavior of the agent for any input?* If yes, ship it. If no, the prompt or the code is wrong — fix both.

— end of agents.md —
