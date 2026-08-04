# ytagent

**An agentic YouTube downloader for cloud-based AI agents.**

[![PyPI version](https://badge.fury.io/py/ytagent-cli.svg)](https://pypi.org/project/ytagent-cli/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub](https://img.shields.io/badge/GitHub-Bilal140202%2Fytagent-black.svg)](https://github.com/Bilal140202/ytagent)

`ytagent` is a deterministic, multi-agent, CLI-first YouTube downloader built specifically for cloud-based AI agents and headless CLIs. It wraps `yt-dlp` in a 13-method fallback chain with a Verifier, Truth Agent, and Tester, and automatically handles the datacenter IP blocks that YouTube imposes.

**One goal:** the calling agent gives us a YouTube URL; we return a path to a verified, playable video file on disk. Everything else is implementation.

---

## Quickstart

```bash
# Install
pip install ytagent-cli

# Download any public YouTube video
ytagent download "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

That's it. The first download auto-bootstraps the BGutil POT provider (one-time ~15-second setup that bypasses YouTube's datacenter-IP blocks). The verified video lands at `downloads/<video_id>.mp4`.

### For AI Agents

```bash
# Print step-by-step instructions an AI agent can follow
ytagent agent-instructions
```

This outputs a complete 10-step guide covering install, setup, download, JSON parsing, bypass methods, self-test, and batch downloads. An AI agent reading ONLY this output can download any public YouTube video without asking a human a single question.

---

## Why this exists

Cloud-based AI agents (like this CLI) cannot:
- Run a browser (no `--cookies-from-browser`)
- Use OAuth (deprecated and removed from yt-dlp)
- Supply cookies (no authenticated session)

And when running on datacenter IPs, YouTube blocks them with "Sign in to confirm you're not a bot" (`LOGIN_REQUIRED`).

`ytagent` solves this by:
1. Using the **`android_vr`** innertube client (JS-less — no n-param deciphering)
2. Auto-loading the **BGutil POT provider** (generates Proof-of-Origin tokens via BotGuard attestation)
3. Walking a **13-method fallback chain** — if one method fails, the next is tried
4. **Verifying** every downloaded file with ffprobe + magic bytes + moov atom checks
5. **Learning** which methods work best in this environment (Truth Agent)
6. **Bypassing datacenter IP blocks** via SOCKS5 proxy farm, Invidious `local=true` proxy, Cobalt community relays, and GitHub Actions remote download farm

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      ytagent CLI (click)                          │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Orchestrator                                   │
│  (walks the fallback chain, hands each result to Verifier)       │
└──────┬───────────────────────┬──────────────────────┬───────────┘
       │                       │                      │
       ▼                       ▼                      ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Truth Agent  │    │   Verifier       │    │     Methods      │
│ (truth.json  │    │ (6-layer file    │    │ (13 tiers):      │
│  + obs.jsonl)│    │  integrity check)│    │  ytdlp_default   │
│              │    │                  │    │  ytdlp_jsless    │
│ Ranks        │    │ 1. size ≥ 1MB    │    │  ytdlp_ios       │
│ methods by   │    │ 2. magic bytes   │    │  ytdlp_single    │
│ observed     │    │ 3. ffprobe       │    │  ytdlp_audio     │
│ success      │    │ 4. duration > 0  │    │  innertube_direct│
│              │    │ 5. stream exists │    │  cobalt          │
│              │    │ 6. moov atom     │    │  cobalt_community│
│              │    │                  │    │  piped           │
│              │    │                  │    │  invidious       │
│              │    │                  │    │  socks5_farm     │
│              │    │                  │    │  github_actions  │
│              │    │                  │    │  transcript_probe│
└──────────────┘    └──────────────────┘    └──────────────────┘
```

---

## The 13-method fallback chain

| Tier | Method | Strategy | When it works |
|---|---|---|---|
| 0 | `transcript_probe` | Preflight reachability check | Always (fast fail if IP is blocked) |
| 1 | `ytdlp_default` | `android_vr` client + BGutil PO token | Residential IPs, whitelisted videos |
| 2 | `ytdlp_jsless` | `visionos, android_vr` clients + BGutil | Same as Tier 1, slightly different path |
| 3 | `ytdlp_ios` | IOS client (HLS) | Sometimes dodges blocks |
| 4 | `ytdlp_single_file` | Pre-muxed MP4 (no ffmpeg merge) | When merge fails or is slow |
| 5 | `ytdlp_audio_only` | Audio-only salvage | Last yt-dlp tier |
| 6 | `innertube_direct` | Hand-rolled POST to `/youtubei/v1/player` | Custom client rotation |
| 7 | `cobalt` | Self-hosted Cobalt sidecar | When running Cobalt locally |
| 8 | `cobalt_community` | Public Cobalt relay instances | **Bypasses datacenter IP block** |
| 9 | `piped` | Piped API with 4-instance rotation | Federated bypass |
| 10 | `invidious` | Invidious `local=true` proxy | **Bypasses datacenter IP block** |
| 11 | `socks5_farm` | Free SOCKS5 proxy discovery (50 parallel) | **Bypasses datacenter IP block** |
| 12 | `github_actions_farm` | Remote download on GitHub runners + WARP | **Bypasses datacenter IP block** |

The Truth Agent ranks these by observed success ratio. After 3 consecutive failures, a method is demoted. After a success, it may be promoted.

---

## CLI reference

```bash
# Download a video
ytagent download <url-or-id> [--out-dir DIR] [--format FMT] [--proxy URL] [--timeout N] [--json]

# One-time setup (auto-runs on first download if missing)
ytagent setup
ytagent setup --status       # check BGutil status
ytagent setup --stop         # stop the auto-started BGutil server

# Show the Truth Agent's learned state
ytagent truth show
ytagent truth reset [--method NAME]

# List all 13 download methods
ytagent list-methods

# Run the end-to-end self-test
ytagent self-test --mode quick    # one video, <2 min
ytagent self-test --mode full     # five videos, ~5 min

# Print step-by-step instructions for AI agents
ytagent agent-instructions              # text format
ytagent agent-instructions --format json
ytagent agent-instructions --format markdown

# Version
ytagent --version
```

### Download options

```bash
ytagent download <url> \
  --out-dir /path/to/save     # default: ./downloads
  --format "best[ext=mp4]"    # override yt-dlp format string
  --proxy http://host:port    # route through a proxy (e.g. Cloudflare WARP)
  --timeout 180               # per-method timeout in seconds
  --json                      # print result as JSON (for AI agents)
```

### JSON output (for AI agents)

```bash
ytagent download <url> --json 2>/dev/null
```

Returns clean JSON on stdout (all logs go to stderr):

```json
{
  "ok": true,
  "video_id": "YOUR_VIDEO_ID",
  "final_path": "downloads/YOUR_VIDEO_ID.mp4",
  "method_used": "ytdlp_default",
  "total_duration_ms": 5432,
  "attempts": [
    {"method": "transcript_probe", "ok": true, "reason": "reachable", ...},
    {"method": "ytdlp_default", "ok": true, "reason": null, ...}
  ],
  "trace_id": "a750a4d4b477"
}
```

---

## How the bypass works (datacenter IP block defeat)

When YouTube blocks your datacenter IP with `LOGIN_REQUIRED`, `ytagent` automatically tries 4 bypass methods:

### 1. Cobalt community relay (Tier 8)
Public Cobalt instances proxy the download through their non-blocked IPs. No self-hosting needed. Proven to bypass the block for ~2 calls per source IP before rate-limiting.

### 2. Invidious `local=true` proxy (Tier 10)
The `local=true` parameter tells Invidious to proxy the googlevideo stream through its own IP. A single `curl` command streams the video through the instance. 360p muxed MP4.

### 3. SOCKS5 proxy farm (Tier 11)
Discovers free SOCKS5 proxies from public lists, tests 50 in parallel with a **two-phase test**:
- Phase 1: Fetch watch page, check `playabilityStatus` is `OK`
- Phase 2: POST to innertube player API, confirm `streamingData` is present

Only proxies passing BOTH phases are used. Then yt-dlp downloads through the working proxy.

### 4. GitHub Actions remote download farm (Tier 12)
Triggers a GitHub Actions workflow that runs on GitHub's Azure runners (residential IPs) with Cloudflare WARP installed. The workflow downloads the video, uploads it as a workflow artifact, and `ytagent` downloads the artifact back to your cloud.

---

## Proof of work

The system has been tested end-to-end in a real cloud environment with a
datacenter IP that YouTube blocks with `LOGIN_REQUIRED`. The testing covered
three scenarios:

1. **Whitelisted video download** — a popular, widely-embedded video was
   downloaded successfully via the `ytdlp_default` method (android_vr client +
   BGutil PO token) in under 5 seconds.

2. **Blocked video batch** — a batch of 10 public videos that were all
   initially blocked (`LOGIN_REQUIRED` across all direct methods) was
   re-tested with the bypass architecture. 9 out of 10 downloaded
   successfully via the SOCKS5 proxy farm and Invidious `local=true` methods.

3. **Agent instructions test** — an AI agent following the `ytagent
   agent-instructions` guide downloaded a previously-blocked video with zero
   human intervention via the `socks5_farm` method.

All downloaded files were verified by the 6-layer Verifier (file size, magic
bytes, ffprobe, duration, stream presence, moov atom).

---

## Requirements

- **Python 3.11+**
- **ffmpeg** and **ffprobe** on PATH (for merging >720p and verifying files)
- **Node.js** and **npm** on PATH (for the BGutil POT provider — auto-installed on first run)
- **git** on PATH (for the BGutil clone — auto-run on first run)

On Ubuntu/Debian: `apt install ffmpeg nodejs npm git`

---

## Installation

### From PyPI (recommended)

```bash
pip install ytagent-cli
```

The package name on PyPI is `ytagent-cli` (because `ytagent` was taken). The CLI command is `ytagent`.

### From source

```bash
git clone https://github.com/Bilal140202/ytagent.git
cd ytagent
pip install -e .
```

### From GitHub directly

```bash
pip install git+https://github.com/Bilal140202/ytagent.git@bypass-proxy-farm
```

---

## For AI agents

### Quick start (3 commands)

```bash
pip install ytagent-cli
ytagent download "https://www.youtube.com/watch?v=VIDEO_ID" --json
```

### Full guide

```bash
ytagent agent-instructions
```

This prints a 10-step guide covering everything from install to batch downloads. An AI agent reading ONLY this output can use ytagent end-to-end without any human help.

### Programmatic usage

```python
import subprocess, json

result = subprocess.run(
    ["ytagent", "download", url, "--json"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
if data["ok"]:
    print(f"Video saved to: {data['final_path']}")
    print(f"Method used: {data['method_used']}")
else:
    for attempt in data["attempts"]:
        print(f"  {attempt['method']}: {attempt['reason']}")
```

---

## Documentation (for developers and AI agents working on ytagent itself)

| File | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Master orientation — read this first if you're modifying ytagent |
| [`agents.md`](agents.md) | Perfection-based role prompts for Orchestrator / Verifier / Truth / Tester |
| [`techstack.md`](techstack.md) | Every dependency, why it's here, upgrade policy |
| [`phases.md`](phases.md) | 6-phase build plan |
| [`plan.md`](plan.md) | Checkable master plan with risk register |
| [`skills.md`](skills.md) | Skill-based prompting reference |
| [`docs/research-blog.md`](docs/research-blog.md) | In-depth research document on the architecture and findings |
| [`.github/workflows/yt-download-farm.yml`](.github/workflows/yt-download-farm.yml) | GitHub Actions remote download worker |

---

## Constraints (non-negotiable)

1. **No cookies. No OAuth. No browser sessions.** Public videos only.
2. **No GUI. No interactive prompts.** 100% non-interactive CLI.
3. **No LLM at runtime.** Deterministic state machine.
4. **Fallback is mandatory.** Walk the chain on failure.
5. **Verification is mandatory.** Every download passes 6 checks.
6. **Files stay under the project directory.**

---

## License

MIT. See [`LICENSE`](LICENSE).

---

## Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — the download engine
- [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) — PO token generation that makes datacenter-IP downloads possible
- [Cobalt](https://github.com/imputnet/cobalt) — alternative download API and community relays
- [Piped](https://github.com/TeamPiped/Piped) — federated YouTube frontend
- [Invidious](https://github.com/iv-org/invidious) — privacy-friendly YouTube frontend with `local=true` proxy
- [TheSpeedX/PROXY-List](https://github.com/TheSpeedX/PROXY-List) — free SOCKS5 proxy lists

---

## Links

- **PyPI:** https://pypi.org/project/ytagent-cli/
- **GitHub:** https://github.com/Bilal140202/ytagent
- **Issues:** https://github.com/Bilal140202/ytagent/issues
- **Releases:** https://github.com/Bilal140202/ytagent/releases
