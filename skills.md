# skills.md — Skill-Based Prompting Reference for `ytagent`

> This file frames the system as a set of **discrete, composable skills** — each one a tightly-scoped capability with a clear input, output, and contract. Skills are how an AI agent (the one calling `ytagent`, or the one building it) should think about what the system can do.
>
> This file is the bridge between the role prompts in `agents.md` and the actual code in `src/ytagent/`. Each skill maps to one or more code modules.

---

## What is a "skill" here?

A skill is **not** an LLM-tool-call interface. It is a documentation unit that says: *"This system can do X, given Y, producing Z, with these guarantees."* Skills are the vocabulary for talking about the system's capabilities without coupling to implementation.

Each skill has:
- **Name** — short, verb-noun.
- **Intent** — one sentence.
- **Input** — what it needs.
- **Output** — what it returns.
- **Guarantees** — invariants that always hold.
- **Implemented by** — the code module(s).
- **Used by** — which agent(s) call it.

---

## Skill 1: `resolve_video_id`

- **Intent:** Turn any YouTube URL shape (or bare ID) into a canonical 11-character video ID.
- **Input:** A string `target` that is one of: `watch?v=`, `youtu.be/`, `/embed/`, `/shorts/`, `/v/`, or a bare 11-char ID.
- **Output:** An 11-character string `[A-Za-z0-9_-]{11}`.
- **Guarantees:** Idempotent. Raises `ValueError` only if the input matches no known shape. Never makes a network call.
- **Implemented by:** `src/ytagent/utils/ids.py`
- **Used by:** Orchestrator (at the start of every `download()`).

## Skill 2: `rank_methods`

- **Intent:** Return the ordered list of download methods to try, ranked by observed success in this environment.
- **Input:** Nothing (reads `state/truth.json`).
- **Output:** `list[str]` of method names, best-first.
- **Guarantees:** Always returns at least the static baseline chain. Never includes a method not in `METHOD_REGISTRY`. Deterministic given the same `truth.json`.
- **Implemented by:** `src/ytagent/agents/truth.py::TruthAgent.ranked_methods`
- **Used by:** Orchestrator.

## Skill 3: `record_observation`

- **Intent:** Append a structured observation about a method attempt to the audit log and update rankings.
- **Input:** An `Observation(ts, video_id, method, ok, reason, bytes, duration_ms)`.
- **Output:** None (side effect: appends to `observations.jsonl`, mutates in-memory `truth.json` counters, may demote/promote).
- **Guarantees:** Append-only — never loses prior observations. Atomic write to `truth.json`. Never raises (catches its own IO errors and logs them).
- **Implemented by:** `src/ytagent/agents/truth.py::TruthAgent.record_observation`
- **Used by:** Orchestrator (after every method attempt).

## Skill 4: `verify_file`

- **Intent:** Confirm a file on disk is a real, playable, non-truncated video.
- **Input:** A `Path` to a file.
- **Output:** A `VerifyResult(ok, reason, duration_s, size_bytes, container, video_codec, audio_codec)`.
- **Guarantees:** Read-only — never mutates the file. Completes in < 10 seconds. Runs all 6 checks fail-fast. Never raises (catches ffprobe failures and returns `ok=False`).
- **Implemented by:** `src/ytagent/agents/verifier.py::Verifier.verify`
- **Used by:** Orchestrator (after every successful method claim).

## Skill 5: `download_video`

- **Intent:** Download a YouTube video to a verified file on disk.
- **Input:** `target` (URL or ID), `out_dir`, optional `opts` (format, sidecar URLs, timeout overrides).
- **Output:** A `DownloadResult(ok, video_id, final_path, method_used, attempts, total_duration_ms)`.
- **Guarantees:** Walks the entire fallback chain on failure. Verifier gates every success. Final file is atomically moved to `out_dir/<video_id>.<ext>`. Never raises — failures are captured in `attempts`. Never asks the user a question.
- **Implemented by:** `src/ytagent/orchestrator.py::Orchestrator.download`
- **Used by:** CLI (`ytagent download`), Tester.

## Skill 6: `try_method`

- **Intent:** Run a single download method in isolation, with a hard timeout, and return its result.
- **Input:** A `Method` callable, a `video_id`, an `out_dir`, an `opts` dict, a `timeout_s`.
- **Output:** A `MethodResult(ok, path, reason, duration_ms, bytes_downloaded)`.
- **Guarantees:** Never raises — catches all exceptions and converts to `ok=False`. Respects the timeout. Writes only to `out_dir`.
- **Implemented by:** Orchestrator's internal `_try_method` helper.
- **Used by:** Orchestrator (once per method in the chain).

## Skill 7: `self_test`

- **Intent:** Prove the system works end-to-end against known-stable public videos.
- **Input:** A mode (`"quick"` or `"full"`).
- **Output:** A `TestReport(started_at, finished_at, mode, results, exit_code)` and a markdown report at `state/self-test-<ts>.md`.
- **Guarantees:** Never hammers YouTube (5s sleep between videos in `--full`). Deletes downloaded files after verifying. Distinguishes "system broken" from "YouTube unreachable".
- **Implemented by:** `src/ytagent/agents/tester.py::Tester.run`
- **Used by:** CLI (`ytagent --self-test`).

## Skill 8: `probe_reachability`

- **Intent:** Quickly check if a video is reachable from this IP without downloading video bytes.
- **Input:** A `video_id`.
- **Output:** A `MethodResult` where `ok=True` means "video is reachable, downstream tiers should try", `ok=False` means "video is unreachable, downstream tiers will likely fail too".
- **Guarantees:** Completes in < 5 seconds. Uses the transcript endpoint (separate rate-limit bucket). Never downloads video bytes.
- **Implemented by:** `src/ytagent/methods/transcript_probe.py`
- **Used by:** Orchestrator (as Tier 0).

## Skill 9: `download_via_ytdlp`

- **Intent:** Download a video using yt-dlp with a given client configuration.
- **Input:** A `video_id`, `out_dir`, `opts` containing `player_client` list, `format` string, and optional `proxy` URL.
- **Output:** A `MethodResult`.
- **Guarantees:** Never raises — catches yt-dlp exceptions. Uses cloud-friendly defaults (`--no-cache-dir`, `--no-check-certificates`, retries). Writes `+faststart` MP4s. Respects the per-method timeout.
- **Implemented by:** `methods/ytdlp_default.py`, `methods/ytdlp_jsless.py`, `methods/ytdlp_ios.py`, `methods/ytdlp_single_file.py`, `methods/ytdlp_audio_only.py`.
- **Used by:** Orchestrator (Tiers 1-4).

## Skill 10: `download_via_innertube`

- **Intent:** Download a video by directly POSTing to YouTube's `/youtubei/v1/player` endpoint and fetching the returned stream URL.
- **Input:** A `video_id`, `out_dir`, `opts` containing `client` (default `"tvhtml5"`) and `fallback_client` (default `"android"`).
- **Output:** A `MethodResult`.
- **Guarantees:** Never raises. Tries the primary client, then the fallback client. Streams the response to disk with `requests` streaming + 10 MB chunks. Skips clients that require signature deciphering (no JS interpreter).
- **Implemented by:** `src/ytagent/methods/innertube_direct.py`
- **Used by:** Orchestrator (Tier 5).

## Skill 11: `download_via_cobalt`

- **Intent:** Download a video by POSTing to a self-hosted Cobalt sidecar.
- **Input:** A `video_id` (or URL), `out_dir`, `opts` containing `cobalt_url` (default `http://127.0.0.1:9000`).
- **Output:** A `MethodResult`.
- **Guarantees:** Fails fast (2s timeout) if the sidecar isn't running — does NOT hang. Handles `redirect`, `tunnel`, and `local-processing` response types.
- **Implemented by:** `src/ytagent/methods/cobalt.py`
- **Used by:** Orchestrator (Tier 6).

## Skill 12: `download_via_piped`

- **Intent:** Download a video by querying a rotated list of Piped API instances.
- **Input:** A `video_id`, `out_dir`, `opts` containing `instances` list (default: 4 known-good instances).
- **Output:** A `MethodResult`.
- **Guarantees:** Tries each instance in order. Skips instances that 429 or 5xx. Muxes video+audio with ffmpeg if only separate streams are available.
- **Implemented by:** `src/ytagent/methods/piped.py`
- **Used by:** Orchestrator (Tier 7).

## Skill 13: `download_via_invidious`

- **Intent:** Download a 360p muxed MP4 via an Invidious instance's `latest_version` redirect.
- **Input:** A `video_id`, `out_dir`, `opts` containing `instances` list.
- **Output:** A `MethodResult`.
- **Guarantees:** Last resort. Low quality (360p). Tries each instance in order.
- **Implemented by:** `src/ytagent/methods/invidious.py`
- **Used by:** Orchestrator (Tier 8).

## Skill 14: `structured_log`

- **Intent:** Emit a structured log line tied to the current `trace_id`.
- **Input:** A `level`, a `message`, an optional `**fields` dict.
- **Output:** None (writes JSONL to stderr, rich-formatted summary to stdout).
- **Guarantees:** Every line includes `ts`, `level`, `trace_id`, `msg`. Never raises. Thread-safe.
- **Implemented by:** `src/ytagent/log.py`
- **Used by:** Every agent and method.

## Skill 15: `atomic_state_write`

- **Intent:** Write a JSON file atomically (write to temp, `os.replace`).
- **Input:** A `Path`, a JSON-serializable `dict`.
- **Output:** None.
- **Guarantees:** The file is never left in a corrupted state, even if the process is killed mid-write. The temp file is cleaned up on failure.
- **Implemented by:** `src/ytagent/state.py::atomic_write_json`
- **Used by:** Truth Agent.

## Skill 16: `parse_youtube_url`

- **Intent:** Extract a video ID from any YouTube URL shape.
- **Input:** A URL string.
- **Output:** An 11-char ID or `None`.
- **Guarantees:** Handles `watch?v=`, `youtu.be/`, `/embed/`, `/shorts/`, `/v/`, `?vi=`, plus playlist URLs (`&list=...` should not break extraction).
- **Implemented by:** `src/ytagent/utils/ids.py::parse_youtube_url`
- **Used by:** `resolve_video_id` skill.

---

## Skill composition map

```
                ┌─────────────────────┐
                │  CLI (click)        │
                │  src/ytagent/cli.py │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  Skill 5:           │
                │  download_video     │
                │  (Orchestrator)     │
                └──┬───────┬───────┬──┘
                   │       │       │
            ┌──────▼──┐ ┌──▼──┐ ┌──▼──────────┐
            │ Skill 1 │ │S 14 │ │ Skill 4:    │
            │ resolve │ │ log │ │ verify_file │
            │ _id     │ └─────┘ │ (Verifier)  │
            └────┬────┘         └─────────────┘
                 │
                 ▼
        ┌────────────────┐
        │ Skill 2:       │      ┌────────────────────┐
        │ rank_methods   │◄────►│ Skill 3:           │
        │ (Truth Agent)  │      │ record_observation │
        └────────┬───────┘      │ (Truth Agent)      │
                 │              └────────────────────┘
                 ▼
   ┌─────────────────────────────────────────────┐
   │  Skill 6: try_method (per method in chain)  │
   └─┬──────┬──────┬──────┬──────┬──────┬────────┘
     │      │      │      │      │      │
     ▼      ▼      ▼      ▼      ▼      ▼
   [S8]   [S9]   [S9]   [S9]   [S10]  [S11/12/13]
   probe  ytdlp  ytdlp  ytdlp  inner  cobalt/
          def   jsless  audio  tube   piped/
                              ios    inv
```

(ASCII schematic; not strict UML.)

---

## How skills map to the fallback chain

| Tier | Skill(s) used | Notes |
|---|---|---|
| 0 | S8 (`probe_reachability`) | Fast preflight |
| 1 | S9 (`download_via_ytdlp`) with default clients | `visionos, android_vr, web` |
| 1b | S9 with `player_client=[visionos, android_vr]` | JS-less only |
| 2 | S9 with `player_client=[ios]` | HLS dodge |
| 3 | S9 with `format='best[ext=mp4]/best'` | No merge, fast |
| 4 | S9 with `format='bestaudio'` | Salvage audio |
| 5 | S10 (`download_via_innertube`) | TVHTML5 → ANDROID sub-fallback |
| 6 | S11 (`download_via_cobalt`) | Self-hosted sidecar |
| 7 | S12 (`download_via_piped`) | 4-instance rotation |
| 8 | S13 (`download_via_invidious`) | 360p last resort |

---

## Skill quality bar

A skill is "done" when:

1. It has an entry in this file (intent, input, output, guarantees, implemented by, used by).
2. The implementing module exists and exports the function with the documented signature.
3. There is at least one unit test that exercises the documented guarantee.
4. The function never raises — all exceptions are caught and converted to a structured failure result.
5. The function logs via Skill 14 (`structured_log`) with its skill name in the `skill` field.
6. The function is referenced by at least one other skill or by the CLI.

— end of skills.md —
