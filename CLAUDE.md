# CLAUDE.md — Master Orientation for AI Assistants Working on `ytagent`

> This file is the single source of truth for any AI agent (Claude, GLM, Gemini, Cursor, Copilot, etc.) that touches this repository. Read it first. Read it completely. Do not skim.

---

## 0. What this project is

**`ytagent`** is a **deterministic, multi-agent, CLI-first YouTube downloader built specifically for cloud-based AI agents and headless CLIs.**

It is **not** a chatbot. It is **not** a wrapper around `yt-dlp` that asks an LLM what to do. It is a hard-coded, state-machine-driven orchestrator that delegates to specialized in-process agents (Verifier, Truth, Tester) and walks a multi-method fallback chain until a verified video file lands on disk.

**One simple goal, repeated like a mantra**: *the calling agent gives us a YouTube URL or video ID; we return a path to a verified, playable video file on disk. Everything else is implementation detail.*

## 1. The non-negotiable constraints (do not violate, do not question)

These constraints are **the contract**. They were given by the user at project inception and are not up for debate. If you find yourself wanting to relax one, stop and re-read this section.

1. **No cookies. No browser sessions. No OAuth. No login flows.**
   The cloud agent that calls us has no authenticated browser. We work for **public** videos only. Age-restricted, members-only, and private videos are explicitly out of scope. Do not add cookie support. Do not add OAuth. Do not ask the user to log in.

2. **No GUI. No interactive prompts. No `input()` calls in the download path.**
   The CLI must be 100% non-interactive. Every decision the system makes must be derivable from the URL + flags + on-disk state. If a method needs human input, it is the wrong method.

3. **No LLM at runtime.**
   The Orchestrator, Verifier, Truth, and Tester agents are **Python functions**, not LLM calls. The "agent" vocabulary is about role separation, not about chat. Determinism is the point — the same input must always produce the same output (modulo network conditions).

4. **Fallback is mandatory.**
   If the primary method fails, we try the next one. And the next. And the next. We do not stop at the first failure and we do not ask the user what to do. We exhaust the chain, and only if every tier fails do we return a structured error explaining what we tried.

5. **Verification is mandatory.**
   A downloaded file is not "done" until the Verifier has confirmed it is a real, playable video: file exists, size > 1 MB, magic bytes are a known video container, `ffprobe` succeeds, duration > 0, and (for MP4) the `moov` atom is present and intact. A 0-byte file or a truncated download is a failure that triggers the next fallback tier.

6. **Files always go under `/home/z/my-project/` (or a path the caller explicitly passed).**
   Never write to `/tmp`, `~`, or any system directory. The default download directory is `/home/z/my-project/ytagent/downloads/`. Override with `--out-dir`.

7. **Truth is a file on disk, not a feeling.**
   `state/truth.json` records which methods have historically worked from this environment, ranked by observed success ratio. The Truth Agent reads it before every download to decide the order of methods. The Orchestrator appends observations to `state/observations.jsonl` after every attempt. Over time the system learns what works *for this specific IP / region / time-of-day*.

8. **YouTube changes; we adapt.**
   The single biggest source of breakage is YouTube rotating their player JS, tightening PO-token enforcement, or blocking a client. When something breaks, the fix is almost always: (a) upgrade `yt-dlp` to the latest release, (b) try a different `player_client`, (c) route through Cloudflare WARP. The Truth Agent is the feedback loop that surfaces this.

## 2. Repository layout (memorize this)

```
ytdl-agent/
├── CLAUDE.md                     # ← you are here
├── agents.md                     # role prompts for Orchestrator / Verifier / Truth / Tester
├── techstack.md                  # every dep, why it's here, what it costs
├── phases.md                     # build phases (research → scaffold → methods → test → ship)
├── plan.md                       # the master plan with checkboxes
├── skills.md                     # the "skills" the system embodies (for skill-based prompting)
├── README.md                     # user-facing quickstart
├── pyproject.toml                # packaging + entry point
├── docker-compose.sidecars.yml   # BGutil POT provider + Cloudflare WARP + Cobalt (optional)
│
├── src/ytagent/
│   ├── __init__.py
│   ├── cli.py                    # the `ytagent` CLI entry point (click-based)
│   ├── orchestrator.py           # the main loop — tries methods in order, hands to Verifier
│   ├── log.py                    # structured logger (JSONL + console via rich)
│   ├── state.py                  # truth.json + observations.jsonl atomic read/write
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── verifier.py           # 6-layer file integrity check (magic / ffprobe / moov)
│   │   ├── truth.py              # reads truth.json, returns ranked method list, demotes failures
│   │   └── tester.py             # self-test against known-stable CC/public-domain videos
│   │
│   ├── methods/                  # one module per download method
│   │   ├── __init__.py           # registry: METHOD_REGISTRY dict
│   │   ├── base.py               # MethodResult dataclass + base interface
│   │   ├── transcript_probe.py   # Tier 0 — preflight reachability check
│   │   ├── ytdlp_default.py      # Tier 1 — yt-dlp default chain (visionos,android_vr,web)
│   │   ├── ytdlp_jsless.py       # Tier 1 alt — explicit JS-less clients only
│   │   ├── ytdlp_ios.py          # Tier 2 — ios client (HLS, sometimes bypasses blocks)
│   │   ├── ytdlp_single_file.py  # Tier 3 — pre-merged muxed mp4 (no ffmpeg merge)
│   │   ├── ytdlp_audio_only.py   # Tier 4 — last-resort: at least get the audio
│   │   ├── innertube_direct.py   # Tier 5 — hand-rolled POST to /youtubei/v1/player
│   │   ├── cobalt.py             # Tier 6 — self-hosted Cobalt API
│   │   ├── piped.py              # Tier 7 — Piped API with instance rotation
│   │   └── invidious.py          # Tier 8 — Invidious latest_version redirect
│   │
│   └── utils/
│       ├── __init__.py
│       ├── ff.py                 # ffmpeg/ffprobe wrappers
│       ├── net.py                # shared requests.Session, retries, UA
│       └── ids.py                # extract video ID from any YouTube URL shape
│
├── tests/
│   ├── conftest.py
│   ├── test_verifier.py          # unit tests for each Verifier layer
│   ├── test_truth.py             # ranking, demote/promote logic
│   ├── test_orchestrator.py      # fallback chain behavior with mocked methods
│   ├── test_ids.py               # URL parsing
│   └── test_e2e.py               # real download against CC video (slow, opt-in via --self-test)
│
├── fixtures/                     # tiny local test videos for Verifier unit tests
│   ├── valid_5s.mp4              # generated by scripts/make_fixtures.py
│   ├── truncated.mp4
│   └── not_a_video.txt
│
├── scripts/
│   ├── make_fixtures.py          # generate test fixtures with ffmpeg
│   └── install_sidecars.sh       # docker compose up -f docker-compose.sidecars.yml
│
├── state/
│   ├── truth.json                # gitignored — per-environment learning
│   └── observations.jsonl        # gitignored — append-only audit log
│
└── downloads/                    # gitignored — where videos land
```

## 3. The agent vocabulary (read this twice)

We use the word "agent" in the **software-engineering sense** (a module with a single responsibility that acts on the world), not in the LLM-marketing sense. There are exactly four agents:

| Agent | Role | Stateful? | Has side effects? |
|---|---|---|---|
| **Orchestrator** | Receive a URL → ask Truth for ranked methods → try each in order → hand result to Verifier → return path or final error | No (per-call) | Yes (writes the downloaded file) |
| **Truth** | Read `state/truth.json` → return ordered list of method names to try → log observations to `state/observations.jsonl` | Yes (state files) | Yes (writes state files) |
| **Verifier** | Given a file path, run 6 layered checks → return `VerifyResult(ok, reason, duration, size, codec)` | No | No (read-only) |
| **Tester** | Run a known-stable video through the whole pipeline → exit 0/1 → optionally write a smoke-test report | No (per-run) | Yes (writes a downloaded file to a temp dir) |

The **Orchestrator is the only agent the CLI calls directly.** The Verifier and Truth are called *by* the Orchestrator. The Tester is called only by `ytagent --self-test`.

## 4. The fallback chain (the heart of the system)

This is the order methods are tried in, by default. The Truth Agent may reorder based on observed success ratios, but this is the static baseline. See `phases.md` for the justification of each tier.

```
Tier 0  transcript_probe      youtube-transcript-api 2s probe; if this 429s, the IP is unreachable — bail.
Tier 1  ytdlp_default         yt-dlp with default client chain (visionos, android_vr, web)
Tier 1b ytdlp_jsless          yt-dlp with --extractor-args player_client=visionos,android_vr  (explicit, no web fallback)
Tier 2  ytdlp_ios             yt-dlp with player_client=ios  (HLS, sometimes dodges blocks)
Tier 3  ytdlp_single_file     yt-dlp with -f 'best[ext=mp4]/best'  (no merge, fastest)
Tier 4  ytdlp_audio_only      yt-dlp with -f 'bestaudio'  (last-resort: at least salvage audio)
Tier 5  innertube_direct      hand-rolled POST to /youtubei/v1/player with TVHTML5 client
Tier 6  cobalt                POST to self-hosted Cobalt sidecar (if running)
Tier 7  piped                 GET /streams/<id> against rotated Piped instances
Tier 8  invidious             curl-style redirect to /latest_version?id=<id>&itag=18  (360p muxed)
```

**Invariants of the chain:**

- Every method returns a `MethodResult(ok, path, reason, duration_ms, bytes_downloaded)`.
- The Orchestrator stops at the first method whose result passes the Verifier.
- If a method "succeeds" (returns a path) but the Verifier rejects the file, that counts as a failure of that method and the Orchestrator proceeds to the next tier.
- The Orchestrator never reuses a file path between methods — each method writes to a unique temp path under `downloads/.tmp/<video_id>/<method_name>/`.
- The final successful file is moved (atomically via `os.replace`) to `downloads/<video_id>.<ext>`.

## 5. How to make changes safely

**Before writing code:**

1. Re-read this file (sections 1, 3, 4).
2. Read `agents.md` for the role prompt of the agent you're touching.
3. Read `techstack.md` if you're adding a dependency.
4. Read `phases.md` to know which phase the work belongs to.
5. Run `ytagent --self-test --quick` to confirm green baseline before you start.

**While writing code:**

- Every public function has a docstring with a one-line summary, an `Args:` block, and a `Returns:` block.
- Every method module exports a `download(url_or_id, out_dir, opts) -> MethodResult` function and a `NAME` constant.
- Every method module is registered in `src/ytagent/methods/__init__.py`.
- No method imports another method. Cross-cutting concerns go in `utils/`.
- Logging uses the structured logger from `log.py`, never `print()`.

**After writing code:**

1. Run `pytest tests/ -x` — all green or you don't commit.
2. Run `ytagent --self-test --quick` — must exit 0.
3. Run `ytagent <a-real-public-video-url>` — must produce a verified file.
4. Append an entry to `state/observations.jsonl` documenting what you observed.
5. Update `state/truth.json` only if observed success ratios have materially shifted.

## 6. The 10 commandments (read before every PR)

1. **Thou shalt not add cookies.**
2. **Thou shalt not call an LLM at runtime.**
3. **Thou shalt not skip the Verifier.** A download is not done until verified.
4. **Thou shalt not stop at the first failure.** Walk the chain.
5. **Thou shalt not write outside `/home/z/my-project/`.**
6. **Thou shalt not `print()`.** Use the logger.
7. **Thou shalt not hard-code video IDs in production code.** Test fixtures live in `tests/`.
8. **Thou shalt not trust a method's self-report.** The Verifier is the source of truth.
9. **Thou shalt pin `yt-dlp` to a known-good version** in `pyproject.toml`, and bump deliberately.
10. **Thou shalt append to `observations.jsonl`, never overwrite.** Audit trail is sacred.

## 7. When (not if) YouTube breaks something

Symptom → first action:

| Symptom | First action |
|---|---|
| `Sign in to confirm you're not a bot` | Add Cloudflare WARP sidecar; route through `--proxy http://127.0.0.1:3128` |
| `Unable to decode n-parameter` | `pip install -U yt-dlp`; the player JS regex is stale |
| HTTP 429 on transcript probe | IP is rate-limited; back off 1h; consider WARP |
| 0-byte file from `web` client | PO token missing; switch to `visionos` or `android_vr` client |
| `Unable to extract video data` | yt-dlp is broken upstream; check yt-dlp issue tracker; pin to last known-good |
| Download hangs at 0% | `--socket-timeout 30 --retries 10`; or try a different client |
| ffprobe says `Invalid data found` | File is HTML error page; check the method's HTTP status code handling |

The Truth Agent should auto-detect these patterns and demote the offending method in `truth.json` after 3 consecutive failures.

## 8. How to extend the system (adding a new method)

1. Create `src/ytagent/methods/my_method.py`.
2. Implement `download(url_or_id, out_dir, opts) -> MethodResult`.
3. Set `NAME = "my_method"`.
4. Register in `src/ytagent/methods/__init__.py`'s `METHOD_REGISTRY`.
5. Add a `state/truth.json` entry with `rank: 9` (bottom of the chain by default).
6. Add a unit test in `tests/test_methods_my_method.py` with a mocked HTTP layer.
7. Add an integration test in `tests/test_e2e.py` gated behind `--self-test --full`.
8. Document in `techstack.md` and `phases.md`.

## 9. Glossary

- **PO Token** — Proof-of-Origin token, a BotGuard attestation YouTube requires for some clients. We avoid clients that need it where possible (`visionos`, `android_vr` don't).
- **n-param** — a query param on `videoplayback` URLs that, if not deciphered, throttles the stream to ~50 KB/s. yt-dlp deciphers it via its JS interpreter.
- **SABR** — Server-side ABR, YouTube's DASH-over-HTTPS transport. Modern yt-dlp handles this transparently.
- **Innertube** — YouTube's internal RPC API at `/youtubei/v1/player`. Returns stream URLs given a video ID and client context.
- **JS-less client** — An innertube client (`visionos`, `android_vr`) that doesn't require deciphering the player JS. Faster and more resilient.
- **moov atom** — The MP4 metadata box. If it's at the end of the file and the download is truncated, the file is unplayable. yt-dlp writes `+faststart` by default; our Verifier checks for this.
- **Method** — A named download strategy (e.g. `ytdlp_default`). One Python module per method.
- **Tier** — The position of a method in the fallback chain. Lower = tried first.

## 10. Final word

This system exists because cloud-based AI agents cannot run `yt-dlp` directly with a browser, and need a deterministic, self-healing way to fetch YouTube videos as part of larger workflows. Every design decision flows from that. When in doubt, ask: *does this make the calling agent's life easier or harder?* If easier, ship it. If harder, cut it.

— end of CLAUDE.md —
