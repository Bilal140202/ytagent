# phases.md — Build Phases for `ytagent`

> The project is built in 6 phases. Each phase has a **goal**, a **definition of done**, and an **exit criterion** that must be met before the next phase begins. Phases are not strictly sequential after Phase 3 — methods can be added in any order once the scaffolding exists.

---

## Phase 0 — Research & Documentation

**Goal:** Know everything there is to know about downloading YouTube videos from a headless cloud environment in 2025–2026, and write it down so future agents don't have to re-research.

**Activities:**
- Three parallel research agents investigate: (a) yt-dlp internals + alternative methods, (b) multi-agent orchestration patterns, (c) Innertube API + bypass methods.
- Findings appended to `/home/z/my-project/worklog.md`.
- Six documentation files authored: `CLAUDE.md`, `agents.md`, `techstack.md`, `phases.md`, `plan.md`, `skills.md`.

**Definition of done:**
- All 6 docs exist, are internally consistent, and reference each other correctly.
- The fallback chain in `CLAUDE.md` §4 matches the methods registered in `methods/__init__.py` (once that file exists in Phase 1).
- A new engineer (or AI agent) reading only these 6 files could scaffold the project without asking a single question.

**Exit criterion:** All 6 docs committed to git.

**Status:** ✅ Complete (this is the phase that produced the file you're reading).

---

## Phase 1 — Scaffolding

**Goal:** Stand up the empty project structure, packaging, CLI entry point, and logger. No download logic yet — just the skeleton that compiles, imports, and prints `--version`.

**Activities:**
- Create the directory tree from `CLAUDE.md` §2.
- Write `pyproject.toml` with all dependencies from `techstack.md` §2.
- Implement `src/ytagent/__init__.py` with `__version__`.
- Implement `src/ytagent/log.py` — structured JSONL logger to stderr + `rich` summary to stdout. Must support a `trace_id` field that ties all log lines for a single `download()` call together.
- Implement `src/ytagent/cli.py` — `click`-based CLI with `--version`, `--help`, and stub subcommands (`download`, `truth show`, `truth reset`, `--self-test`).
- Implement `src/ytagent/state.py` — atomic read/write helpers for `state/truth.json` and append-only writer for `state/observations.jsonl`.
- Implement `src/ytagent/utils/ids.py` — `to_video_id(target)` that accepts any of: `https://www.youtube.com/watch?v=ID`, `https://youtu.be/ID`, `https://www.youtube.com/embed/ID`, `https://www.youtube.com/shorts/ID`, or a bare 11-char ID. Returns the ID or raises `ValueError`.
- Implement `src/ytagent/utils/net.py` — shared `requests.Session` with retry adapter, sensible UA, `--no-check-certificates` equivalent.
- Implement `src/ytagent/utils/ff.py` — wrappers around `ffmpeg` and `ffprobe` with timeouts.
- `pip install -e .` succeeds. `ytagent --version` prints `ytagent 0.1.0`.

**Definition of done:**
- `ytagent --version` works.
- `ytagent --help` lists all subcommands.
- `ytagent download <url>` raises `NotImplementedError` with a clear message.
- `pytest tests/` passes (tests are stubs that just import modules).
- `ruff check .` is clean.

**Exit criterion:** Skeleton committed. `ytagent --version` exits 0.

**Status:** 🚧 In progress.

---

## Phase 2 — The Four Agents (no methods yet)

**Goal:** Implement the Orchestrator, Truth, Verifier, and Tester agents in full, with unit tests. Methods are mocked — the goal is to prove the orchestration logic works.

**Activities:**
- Implement `src/ytagent/agents/verifier.py` per `agents.md` Agent 3. All 6 checks. Use `python-magic` for check 2, `ffprobe` for checks 3-6.
- Implement `src/ytagent/agents/truth.py` per `agents.md` Agent 2. Default `truth.json` written on first read. Atomic writes. Demote/promote logic.
- Implement `src/ytagent/orchestrator.py` per `agents.md` Agent 1. Walk the chain. Hand to Verifier. Move on success.
- Implement `src/ytagent/agents/tester.py` per `agents.md` Agent 4. `--quick` and `--full` modes.
- Write `tests/test_verifier.py` — use `fixtures/valid_5s.mp4`, `fixtures/truncated.mp4`, `fixtures/not_a_video.txt`. Test each of the 6 checks individually and in combination.
- Write `tests/test_truth.py` — test ranking, demote after 3 failures, promote after success, atomic write under crash.
- Write `tests/test_orchestrator.py` — with a `FakeMethod` that succeeds/fails/raises, verify the Orchestrator walks the chain correctly and produces a `DownloadResult` with the right `attempts` list.
- Generate fixtures via `scripts/make_fixtures.py` (uses `ffmpeg -f lavfi -i testsrc=duration=5 ...`).

**Definition of done:**
- All unit tests pass.
- Coverage ≥ 85% on `src/ytagent/agents/` and `src/ytagent/orchestrator.py`.
- `ytagent download <url>` with a mocked method produces a verified file at the right path.
- The Verifier correctly rejects each fixture type.
- The Truth Agent correctly demotes a method after 3 failures and writes the change atomically.

**Exit criterion:** `pytest tests/ -x --cov=ytagent` passes with ≥85% coverage.

**Status:** ⏳ Pending Phase 1.

---

## Phase 3 — Method Backends (the meat)

**Goal:** Implement every download method in the fallback chain. Each method is a self-contained module that conforms to the `Method` interface and never raises.

**Activities (in priority order):**

### 3.1 Tier 0 — `methods/transcript_probe.py`
- Uses `requests` to hit `https://www.youtube.com/youtubei/v1/...` or the simpler `youtube-transcript-api`-style endpoint.
- Returns `ok=True` if the video is reachable from this IP, `ok=False` with a clear reason if 429'd or "Video unavailable".
- Does NOT actually download video bytes. This is a preflight.
- **Why first**: Separate rate-limit bucket; fast; if this fails, no other tier will help.

### 3.2 Tier 1 — `methods/ytdlp_default.py`
- Wraps `yt_dlp.YoutubeDL` with the cloud-friendly options from `techstack.md` and the research.
- Default format string: `bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[acodec^=mp4a][ext=m4a]/best[ext=mp4]/best`.
- Options: `no_cache_dir`, `nocheckcertificate`, `socket_timeout=30`, `retries=10`, `fragment_retries=10`, `extractor_retries=3`, `ignoreerrors=True`, `no_warnings=True`, `quiet=True`, `merge_output_format='mp4'`, `postprocessor_args={'ffmpeg': ['-movflags', '+faststart']}`.
- Captures yt-dlp's progress hooks to log bytes downloaded.
- Returns `MethodResult(ok=True, path=...)` on success.

### 3.3 Tier 1b — `methods/ytdlp_jsless.py`
- Same as 3.2 but with `extractor_args={'youtube': {'player_client': ['visionos', 'android_vr']}}` — explicitly JS-less, no `web` fallback.
- Faster (no JS interpreter spun up). Slightly less reliable on edge cases.

### 3.4 Tier 2 — `methods/ytdlp_ios.py`
- Same as 3.2 but with `player_client=ios`.
- Returns HLS m3u8 streams; yt-dlp handles the segment fetching.
- Sometimes dodges blocks that affect `web`.

### 3.5 Tier 3 — `methods/ytdlp_single_file.py`
- Format string: `best[ext=mp4]/best` — no merge, fastest path.
- Yields ≤720p muxed MP4. Use when ffmpeg merge is failing or slow.

### 3.6 Tier 4 — `methods/ytdlp_audio_only.py`
- Format string: `bestaudio[ext=m4a]/bestaudio` — salvage at least the audio.
- The Verifier accepts audio-only files (check 5 allows `codec_type=audio`).
- Last yt-dlp-based tier.

### 3.7 Tier 5 — `methods/innertube_direct.py`
- Hand-rolled `requests.post` to `https://www.youtube.com/youtubei/v1/player?key=...`.
- Uses the `TVHTML5` client context (research says it's currently PO-token-light).
- Parses `streamingData.formats` and `adaptiveFormats`.
- Picks the best mp4 stream URL, downloads it with `requests` streaming.
- No JS interpreter — relies on the client not requiring signature deciphering.
- **Fallback within the method**: if TVHTML5 returns throttled/empty, try `ANDROID` client as a sub-fallback before giving up.

### 3.8 Tier 6 — `methods/cobalt.py`
- `POST http://127.0.0.1:9000/` with `{"url": ..., "videoQuality": "1080", "youtubeVideoCodec": "h264", "youtubeVideoContainer": "mp4", "downloadMode": "auto"}`.
- If `status == "redirect"`, download the URL via `requests`.
- If `status == "tunnel"`, stream through cobalt.
- If cobalt isn't running (connection refused), return `ok=False, reason="cobalt sidecar not running"` immediately — don't hang.

### 3.9 Tier 7 — `methods/piped.py`
- Instance list: `pipedapi.kavin.rocks`, `pipedapi.adminforge.de`, `pipedapi.leptons.xyz`, `pipedapi.r4fo.com`.
- `GET https://<instance>/streams/<video_id>` → parse JSON → pick `videoStreams[videoOnly=false][0]` or mux video+audio.
- If a 429 or 5xx from one instance, try the next.

### 3.10 Tier 8 — `methods/invidious.py`
- Instance list: `yewtu.be`, `invidious.nerdvpn.de`, `inv.nadeko.net`.
- `GET https://<instance>/latest_version?id=<id>&itag=18` → follows redirect → 360p muxed mp4.
- Last resort. Often flaky.

### 3.11 Method registry
- `methods/__init__.py` exports `METHOD_REGISTRY: dict[str, Method]` mapping names to module functions.
- Each method module exports `NAME` and `download()`.

**Definition of done:**
- Every method module exists and conforms to the interface.
- `METHOD_REGISTRY` contains all 10 methods.
- Each method has at least one unit test (mocked HTTP for non-yt-dlp methods; mocked `YoutubeDL` for yt-dlp methods).
- `ytagent download <real-public-video-url>` succeeds using at least Tier 1.

**Exit criterion:** `pytest tests/` passes. At least one real public video downloads end-to-end via `ytagent download`.

**Status:** ⏳ Pending Phase 2.

---

## Phase 4 — End-to-end testing & proof of work

**Goal:** Prove the system works against real YouTube, with real videos, on this cloud environment. Generate the proof-of-work artifacts that get pushed to GitHub.

**Activities:**
- Run `ytagent --self-test --quick` against the corpus. Must exit 0.
- Run `ytagent --self-test --full` against the full corpus. Generate `state/self-test-<timestamp>.md`.
- Run `ytagent download https://www.youtube.com/watch?v=BaW_jenozKc --out-dir downloads/proof/` and confirm a verified file lands in `downloads/proof/`.
- Capture the JSONL log of a successful download as `docs/proof-of-work/sample-run.jsonl`.
- Capture the Verifier's verdict on the downloaded file as `docs/proof-of-work/verify-result.json`.
- Write `docs/proof-of-work/README.md` explaining what was tested, when, and what the results were.

**Definition of done:**
- `state/self-test-<timestamp>.md` exists and shows all corpus videos passing.
- `downloads/proof/` contains a verified video.
- `docs/proof-of-work/` contains the sample run log, the verify result, and the README.

**Exit criterion:** A downstream reader of `docs/proof-of-work/` is convinced the system works.

**Status:** ⏳ Pending Phase 3.

---

## Phase 5 — Sidecars & escape hatches

**Goal:** Document and provide the optional infrastructure (BGutil, WARP, Cobalt) for when YouTube tightens. Not required for v1, but ready to switch on.

**Activities:**
- Write `docker-compose.sidecars.yml` with all three services.
- Write `scripts/install_sidecars.sh` that brings them up.
- Document in `README.md` how to enable `--proxy http://127.0.0.1:3128` and `--extractor-args 'youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416'`.
- Add CLI flags `--warp`, `--bgutil`, `--cobalt-url` that wire these up automatically.

**Definition of done:**
- `docker compose -f docker-compose.sidecars.yml up -d` brings up all three services.
- `ytagent download --warp --bgutil <url>` routes through the sidecars.
- Documented in `README.md`.

**Exit criterion:** Sidecar docs and compose file committed. Not required to be running for v1.

**Status:** ⏳ Pending Phase 4 (can be parallelized).

---

## Phase 6 — Polish, packaging, ship

**Goal:** Make `ytagent` installable, documented, and ready for other AI agents to use.

**Activities:**
- Write `README.md` — quickstart, install, usage, examples.
- Write `LICENSE` (MIT).
- Write `CONTRIBUTING.md` (reference `CLAUDE.md` and `agents.md`).
- Write `.gitignore` (state/, downloads/, __pycache__/, *.pyc, .pytest_cache/, .ruff_cache/).
- Write `scripts/Dockerfile` for the agent itself.
- Add `ytagent truth show` and `ytagent truth reset` subcommands.
- Add `ytagent --list-methods` to print the registered method chain.
- Tag `v0.1.0` in git.
- (Future) Publish to PyPI.

**Definition of done:**
- `README.md` has a working quickstart that a fresh user can follow in < 5 minutes.
- `LICENSE`, `CONTRIBUTING.md`, `.gitignore` exist.
- `git tag v0.1.0` exists.

**Exit criterion:** Repo is public-ready. Tag `v0.1.0` pushed.

**Status:** ⏳ Pending Phase 4.

---

## Cross-phase invariants

These must hold at every phase boundary:

1. **`pytest tests/ -x` passes** at every commit. No phase may end with red tests.
2. **`ruff check .` is clean.**
3. **`ytagent --version` works** from Phase 1 onward.
4. **`state/truth.json` is never committed.** It is per-environment.
5. **`state/observations.jsonl` is never committed.** Same.
6. **`downloads/` is never committed.** Same.
7. **Every new method module updates `METHOD_REGISTRY`.**
8. **Every new agent role updates `agents.md`.**
9. **Every new dependency updates `techstack.md`.**
10. **Every phase boundary updates `plan.md` checkboxes.**

— end of phases.md —
