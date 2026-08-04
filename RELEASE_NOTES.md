# Release Notes — ytagent v0.3.0

**Release date:** 2026-08-04
**PyPI package:** `ytagent-cli` v0.3.0
**GitHub tag:** `v0.3.0`
**Branch:** `bypass-proxy-farm`

---

## What's new in v0.3.0

### 1. `ytagent agent-instructions` command

A new CLI command that prints a complete 10-step guide for AI agents:

```
ytagent agent-instructions              # text format (default)
ytagent agent-instructions --format json
ytagent agent-instructions --format markdown
```

The 10 steps cover:
1. Install (`pip install ytagent-cli`)
2. Verify (`ytagent --version`)
3. Setup (`ytagent setup` — auto-installs BGutil)
4. Check status (`ytagent setup --status`)
5. Download (`ytagent download URL --json`)
6. Parse JSON result
7. Download blocked videos (automatic bypass)
8. Self-test
9. Inspect Truth Agent state
10. Batch download

Each step includes: description, exact command, expected output, and failure troubleshooting. An AI agent reading ONLY this output can download any public YouTube video without asking a human a single question.

### 2. `ytagent setup` command

One-command setup that auto-installs the BGutil POT provider:

```
ytagent setup              # clone, npm install, compile, start server
ytagent setup --status     # check if BGutil is ready
ytagent setup --stop       # stop the auto-started server
```

This makes `pip install ytagent-cli && ytagent download <url>` Just Work on a fresh machine. No manual git clone, no manual npm install, no manual server start.

### 3. `socks5_farm` method — two-phase proxy testing

The SOCKS5 proxy farm method now does a **two-phase test** before using a proxy:

- **Phase 1:** Fetch the YouTube watch page through the proxy, check `playabilityStatus` is `OK` (not `LOGIN_REQUIRED`)
- **Phase 2:** POST to the innertube player API, confirm `streamingData` is present (stream URLs are returned)

Only proxies passing BOTH phases are used for download. This prevents finding a proxy that can load the watch page but fails on the player API call.

### 4. `bootstrap.py` module — auto-bootstrap on first download

If BGutil is missing when `ytagent download` runs, it auto-bootstraps:
1. Clones the BGutil repo
2. Runs `npm install --production`
3. Installs TypeScript compiler
4. Compiles the TypeScript
5. Starts the HTTP server on port 4416

All in ~15 seconds. The user never needs to think about BGutil.

### 5. Fixed stdout/stderr separation

All rich console output (INFO, WARN, ERROR, SUCCESS messages) now goes to **stderr**. **stdout** is reserved for machine-readable JSON output when using `--json`. This makes `ytagent download <url> --json | python3 -m json.tool` work cleanly.

### 6. PyPI publishing

The package is published to PyPI as `ytagent-cli`:
```bash
pip install ytagent-cli
```

The CLI command is `ytagent` (not `ytagent-cli`). The import name is `ytagent`.

---

## The 13-method fallback chain

| Tier | Method | Strategy | Bypasses datacenter IP block? |
|---|---|---|---|
| 0 | `transcript_probe` | Preflight reachability check | N/A (fast fail) |
| 1 | `ytdlp_default` | android_vr client + BGutil PO token | No (needs whitelisted video) |
| 2 | `ytdlp_jsless` | visionos + android_vr clients + BGutil | No |
| 3 | `ytdlp_ios` | IOS client (HLS) | Sometimes |
| 4 | `ytdlp_single_file` | Pre-muxed MP4 | No |
| 5 | `ytdlp_audio_only` | Audio-only salvage | No |
| 6 | `innertube_direct` | Direct innertube API call | No |
| 7 | `cobalt` | Self-hosted Cobalt sidecar | Yes (if Cobalt has residential IP) |
| 8 | `cobalt_community` | Public Cobalt relay instances | **Yes** |
| 9 | `piped` | Piped API (4-instance rotation) | Varies |
| 10 | `invidious` | Invidious `local=true` proxy | **Yes** |
| 11 | `socks5_farm` | Free SOCKS5 proxy discovery | **Yes** |
| 12 | `github_actions_farm` | GitHub Actions runners + WARP | **Yes** |

---

## Proof of work

### Test 1: Whitelisted video (Rick Astley)
- **Video:** `dQw4w9WgXcQ`
- **Result:** 243 MB, 213s, AV1/Opus MP4
- **Method:** `ytdlp_default` (android_vr + BGutil)
- **Time:** 4.8 seconds

### Test 2: Babymonster batch (previously blocked)
- **Videos:** 10 Babymonster interviews/documentaries
- **Result:** 9/10 downloaded (605 MB total)
- **Methods:** SOCKS5 proxy farm (8), Invidious local=true (1)
- **1 failure:** `hCgZqFscMP0` (no working proxy found)

### Test 3: Agent instructions test (zero manual steps)
- **Video:** `8Dk63EzXs0w` (previously blocked)
- **Result:** 69.2 MB, 1080p AV1, 591s
- **Method:** `socks5_farm` (two-phase test)
- **Time:** 213 seconds (11 methods failed fast, socks5_farm found proxy in ~100s)
- **Proof:** AI agent followed `ytagent agent-instructions` with zero human intervention

---

## Installation

### From PyPI
```bash
pip install ytagent-cli
```

### From source
```bash
git clone https://github.com/Bilal140202/ytagent.git
cd ytagent
git checkout bypass-proxy-farm
pip install -e .
```

---

## Requirements

- Python 3.11+
- ffmpeg + ffprobe (for video verification and merging)
- Node.js + npm (for BGutil POT provider — auto-installed)
- git (for BGutil clone — auto-run)

---

## Breaking changes from v0.2.0

None. v0.3.0 is fully backward compatible with v0.2.0. All existing commands work the same way. The new methods (cobalt_community, socks5_farm, github_actions_farm) are added to the fallback chain automatically.

---

## Migration guide

If you're on v0.2.0 or earlier:
```bash
pip install --upgrade ytagent-cli
```

No other changes needed. The new methods are automatically tried when the old ones fail.

---

## Known limitations

1. **Free bypass services are unreliable** — Invidious instances and Cobalt relays go up and down. The socks5_farm method is the most reliable bypass.
2. **SOCKS5 proxies are slow** — Free proxies can take 30-120 seconds to find and download through.
3. **Cobalt community relay rate-limits** — ~2 calls per source IP before blocking.
4. **GitHub Actions needs a token** — The `github_actions_farm` method requires `--github-token` in opts.
5. **No age-restricted video support** — Public videos only (by design).

---

## What's next (future versions)

- [ ] PyPI trusted publishing via GitHub Actions CI
- [ ] Oracle Cloud Free Tier self-hosted Cobalt setup script
- [ ] Web UI for batch download management
- [ ] Subtitle/transcript download support
- [ ] Playlist support
- [ ] Progress bars for long downloads

---

## Links

- **PyPI:** https://pypi.org/project/ytagent-cli/0.3.0/
- **GitHub:** https://github.com/Bilal140202/ytagent
- **Changelog:** https://github.com/Bilal140202/ytagent/releases
- **Issues:** https://github.com/Bilal140202/ytagent/issues
