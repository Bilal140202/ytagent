# techstack.md — Technology Stack for `ytagent`

> Every dependency, every tool, every choice — with the **why**, the **cost**, the **failure mode**, and the **upgrade policy**. If a tool is not in this file, it does not belong in the project.

---

## 1. Language & runtime

| Choice | Decision |
|---|---|
| Language | **Python 3.11+** (3.12 preferred) |
| Why | yt-dlp is Python; the entire YouTube-download ecosystem is Python; the calling agent (this CLI) is Python. No reason to introduce a second language. |
| Cost | Interpreter startup ~50 ms (negligible vs. network latency). |
| Failure mode | Python 3.10 lacks `tomllib` and some typing features used. 3.13+ has faster startup but yt-dlp's `jsc/` JS interpreter has had 3.13 regressions in 2025; pin to 3.12 for stability. |
| Upgrade policy | Track CPython 3.12 patch releases. Evaluate 3.13/3.14 only after yt-dlp explicitly supports them. |

## 2. Core dependencies (required at runtime)

### 2.1 `yt-dlp` — the primary download engine

- **Pinned version**: `>=2026.07.04` (latest at time of writing; verified against source in research).
- **Why it's here**: It is the only project that has kept up with YouTube's anti-bot changes since 2021. Maintains a JS interpreter for n-param deciphering, supports the PO Token Provider Framework (added `2025.05.22`), and its default client chain (`visionos` → `android_vr` → `web`) means the first two attempts need no JS, no POT, no cookies — exactly what a cloud agent needs.
- **Cost**: ~30 MB installed, ~80 MB peak RSS during a download with the JS interpreter running.
- **Failure mode**: YouTube rotates player JS ~weekly; yt-dlp's cipher regexes lag by hours-to-days. Symptom: `Unable to decode n-parameter` warning + throttled downloads.
- **Upgrade policy**: **Bump deliberately, not automatically.** Pin in `pyproject.toml`. Subscribe to https://github.com/yt-dlp/yt-dlp/releases.atom. Bump weekly or whenever a download breaks.
- **Used by**: `methods/ytdlp_default.py`, `methods/ytdlp_jsless.py`, `methods/ytdlp_ios.py`, `methods/ytdlp_single_file.py`, `methods/ytdlp_audio_only.py`.

### 2.2 `requests` — HTTP client for non-yt-dlp methods

- **Pinned version**: `>=2.32`.
- **Why**: Needed for the innertube-direct, Cobalt, Piped, and Invidious methods. yt-dlp uses its own HTTP layer; we use `requests` for everything else.
- **Cost**: ~1 MB.
- **Failure mode**: Default `urllib3` retries are inadequate; we wrap with our own retry layer in `utils/net.py`.
- **Upgrade policy**: Track upstream; security-driven bumps only.

### 2.3 `python-magic` — file-type detection by magic bytes

- **Pinned version**: `>=0.4.27`.
- **Why**: The Verifier's check 2 (magic bytes) needs to identify the container format of a downloaded file without trusting the extension. `python-magic` wraps `libmagic`, which is installed on every Linux cloud environment.
- **Cost**: ~50 KB Python + system `libmagic` (already present).
- **Failure mode**: `libmagic` database location varies across distros; we set `MAGIC_FILE` env var defensively.
- **Upgrade policy**: Track upstream.

### 2.4 `click` — CLI framework

- **Pinned version**: `>=8.1` (note: we accept the `gtts` dep conflict — `gtts` is not used by `ytagent`).
- **Why**: Mature, well-documented, supports subcommands (`ytagent download`, `ytagent truth show`, `ytagent --self-test`), type conversion, and help generation.
- **Cost**: ~200 KB.
- **Failure mode**: None significant.
- **Upgrade policy**: Track upstream.

### 2.5 `rich` — terminal output

- **Pinned version**: `>=13.7`.
- **Why**: Pretty, structured console output (tables, progress, colors) for human-readable logs. Used by the Tester for its summary table and by `log.py` for the stdout summary. JSONL goes to stderr for machine consumption; `rich` goes to stdout for humans.
- **Cost**: ~5 MB.
- **Failure mode**: Some terminals don't support 24-bit color; `rich` auto-detects and degrades.
- **Upgrade policy**: Track upstream.

## 3. Optional dependencies (used only when sidecars are running)

### 3.1 `bgutil-ytdlp-pot-provider` — PO Token provider plugin

- **Install**: `pip install bgutil-ytdlp-pot-provider` AND run the Docker container `brainicism/bgutil-ytdlp-pot-provider:latest` on `127.0.0.1:4416`.
- **Why**: When YouTube tightens and the JS-less clients (`visionos`, `android_vr`) start requiring POTs, this plugin auto-mints them via BotGuard attestation in Node.js. We don't need it today (the default chain works), but we keep the install path documented.
- **Cost**: ~20 MB Python + ~150 MB Docker container.
- **Failure mode**: The Node.js process is slow on first call (~3 s for attestation) and can crash on YouTube-side BotGuard changes.
- **Upgrade policy**: Track upstream; bump alongside yt-dlp.

### 3.2 Cloudflare WARP — datacenter IP anonymization

- **Install**: `docker compose -f docker-compose.sidecars.yml up -d warp-proxy` using the `monius/docker-cloudflare-warp` image. Exposes SOCKS5 on `127.0.0.1:1080` and HTTP on `127.0.0.1:3128`.
- **Why**: Cloud/datacenter IPs get the "Sign in to confirm you're not a bot" wall from YouTube. Routing through WARP makes the request appear to come from Cloudflare's residential-ish IP ranges, bypassing the wall.
- **Cost**: ~50 MB Docker container + ~10 Mbps of WARP bandwidth (free tier).
- **Failure mode**: WARP itself can be rate-limited by Cloudflare if abused. Free tier is shared.
- **Upgrade policy**: Track the `monius/docker-cloudflare-warp` image.

### 3.3 Cobalt — self-hostable download proxy

- **Install**: `docker compose -f docker-compose.sidecars.yml up -d cobalt` using `ghcr.io/imputnet/cobalt:latest`. Exposes API on `127.0.0.1:9000`.
- **Why**: An alternative to yt-dlp for the agent — a single `POST /` returns a redirect URL or a tunnel stream. Cobalt internally handles POTs and is updated independently of yt-dlp. Useful as a Tier 6 fallback when yt-dlp's extractor is broken upstream.
- **Cost**: ~100 MB Docker container.
- **Failure mode**: Cobalt has its own breakage cycle; it's a yt-dlp alternative, not a silver bullet.
- **Upgrade policy**: Track `ghcr.io/imputnet/cobalt:latest`.

## 4. Dev / test dependencies

| Package | Version | Purpose |
|---|---|---|
| `pytest` | `>=8.0` | Test runner |
| `pytest-cov` | `>=5.0` | Coverage reporting (target ≥85%) |
| `pytest-mock` | `>=3.12` | Mocking HTTP and method behavior |
| `responses` | `>=0.25` | Mock `requests` calls in unit tests |
| `ruff` | `>=0.5` | Linter + formatter (replaces black + flake8) |
| `mypy` | `>=1.10` | Static type checking |
| `types-requests` | latest | Stubs for `requests` |

## 5. External binaries (must be on `PATH`)

### 5.1 `ffmpeg` and `ffprobe`

- **Required version**: `>=4.4` (any modern Linux distro's version is fine).
- **Why**: yt-dlp uses `ffmpeg` to merge video + audio streams for >720p outputs. The Verifier uses `ffprobe` to inspect downloaded files.
- **Cost**: ~80 MB installed.
- **Failure mode**: If `ffmpeg` is missing, yt-dlp falls back to muxed formats only (≤720p). The Verifier will still work via magic-byte checks but skips check 6 (moov atom walk).
- **Upgrade policy**: Track distro version; no need to pin.

### 5.2 `curl` (optional)

- Used by `methods/invidious.py` for the simple redirect-download pattern. Can be replaced with `requests` if needed.

## 6. Containerization

### 6.1 The agent itself

- **No container required.** `ytagent` is a plain Python CLI. Install via `pipx install ytagent` (once published) or `pip install -e .` from a clone.
- If a container is desired for reproducibility, a `Dockerfile` is provided in `scripts/Dockerfile` based on `python:3.12-slim` with `ffmpeg` installed.

### 6.2 Sidecars (optional)

- `docker-compose.sidecars.yml` defines three optional sidecars (BGutil, WARP, Cobalt). These are NOT required for the system to work; they're escape hatches for when YouTube tightens.

## 7. CI / CD

| Concern | Tool |
|---|---|
| Lint + format | `ruff check . && ruff format --check .` |
| Type check | `mypy src/ytagent` |
| Unit tests | `pytest tests/ -x --cov=ytagent --cov-fail-under=85` |
| E2E smoke test | `python -m ytagent --self-test --quick` (gated, opt-in via `RUN_E2E=1` env var to avoid hammering YouTube from CI) |
| Build | `python -m build` → wheel + sdist |
| Publish | (future) GitHub Release + PyPI on tag push |

## 8. State & storage

| Path | Format | Lifetime | Gitignored? |
|---|---|---|---|
| `state/truth.json` | JSON | Persistent, mutated at runtime | Yes |
| `state/observations.jsonl` | JSONL, append-only | Persistent, grows unbounded | Yes |
| `state/self-test-*.md` | Markdown | Persistent, one per `--self-test` run | Yes |
| `downloads/` | files | Persistent until caller deletes | Yes |
| `downloads/.tmp/<video_id>/<method>/` | files | Ephemeral, cleaned per-Orchestrator-call | Yes |
| `~/.cache/yt-dlp/` | (NOT USED) | — | N/A — we pass `--no-cache-dir` |

## 9. Why we did NOT choose certain tools

| Tool | Why rejected |
|---|---|
| `pytube` | Broken since June 2024. No JS interpreter. No POT handling. Do not use. |
| `pytubefix` | A fork of pytube, slightly more maintained but still single-client (`android`) and no POT. Marginal benefit over yt-dlp's `android` client. |
| `youtube-dl` | Abandoned. Last meaningful release 2021. No PO token support. |
| `gallery-dl` | Delegates to yt-dlp for YouTube. No value-add. |
| `LangGraph` / `AutoGen` / `CrewAI` | All assume an LLM in the loop. We are deterministic. Adds 100+ MB of deps for no benefit. |
| `selenium` / `playwright` | Requires a browser. Violates the no-browser constraint. (Exception: BGutil uses Playwright internally in script mode, but we use HTTP mode which doesn't.) |
| `yt-dlp`'s OAuth login | Removed upstream. Doesn't work. |
| Cookies from a browser profile | Not possible in a headless cloud environment. |

## 10. Dependency tree (top-level)

```
ytagent
├── yt-dlp >= 2026.07.04      # primary engine
├── requests >= 2.32          # HTTP for non-yt-dlp methods
├── python-magic >= 0.4.27    # magic byte detection (Verifier check 2)
├── click >= 8.1              # CLI
├── rich >= 13.7              # pretty console output
└── (optional) bgutil-ytdlp-pot-provider   # POT sidecar plugin

dev:
├── pytest, pytest-cov, pytest-mock
├── responses
├── ruff
└── mypy, types-requests
```

Total install size (without sidecars): ~120 MB. With sidecars (Docker): ~400 MB additional.

## 11. Versioning policy for `ytagent` itself

- **SemVer**: `MAJOR.MINOR.PATCH`.
- `MAJOR`: breaking change to `Orchestrator.download` signature or `MethodResult`/`VerifyResult` schema.
- `MINOR`: new method added, new CLI subcommand, new truth.json field (with default).
- `PATCH`: bug fix, dependency bump, doc update.
- Pre-1.0: anything goes, but document it in `phases.md`.

— end of techstack.md —
