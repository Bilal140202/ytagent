# ytagent

A YouTube downloader built for **cloud-based AI agents**. One command downloads any public YouTube video to a verified file on disk. No cookies, no browser, no logins.

## Install

```bash
pip install ytagent
```

That's it. The first download auto-installs and starts the BGutil POT provider (a one-time ~15-second setup that bypasses YouTube's datacenter-IP blocks).

## Use

```bash
ytagent download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

The verified video lands at `downloads/<video_id>.mp4`.

## How it works (1-minute version)

```
ytagent download <url>
       │
       ▼
  Orchestrator
       │  tries 10 methods in order:
       │   1. transcript probe (reachability check)
       │   2. yt-dlp + android_vr client + BGutil PO token  ← primary path
       │   3. yt-dlp + visionos client
       │   4. yt-dlp + ios client
       │   5. yt-dlp single-file muxed MP4
       │   6. yt-dlp audio-only salvage
       │   7. direct Innertube API call
       │   8. self-hosted Cobalt sidecar
       │   9. Piped API (4-instance rotation)
       │  10. Invidious redirect (360p last resort)
       │
       ▼
  Verifier (6 checks: size, magic bytes, ffprobe, duration, streams, moov atom)
       │
       ▼
  Verified MP4 on disk  ✓
```

If method #2 succeeds, the rest are skipped. If it fails, the next is tried. The Truth Agent remembers which methods work best in your environment and reorders them over time.

## Why this exists

Cloud-based AI agents (like this CLI) cannot:
- Run a browser (no `--cookies-from-browser`)
- Use OAuth (deprecated and removed from yt-dlp)
- Supply cookies (no authenticated session)

And when running on datacenter IPs, YouTube blocks them with "Sign in to confirm you're not a bot". `ytagent` solves this by:

1. Using the **`android_vr`** innertube client (JS-less — no n-param deciphering needed)
2. Auto-loading the **BGutil POT provider** (generates Proof-of-Origin tokens via BotGuard attestation, which lifts the LOGIN_REQUIRED block)
3. Walking a **10-method fallback chain** — if one fails, the next is tried
4. **Verifying** every download with ffprobe + magic bytes + moov atom checks
5. **Learning** which methods work best in this environment (Truth Agent)

## Commands

```bash
# Download a video
ytagent download <url-or-id>

# One-time setup (auto-runs on first download if missing)
ytagent setup
ytagent setup --status       # check BGutil status
ytagent setup --stop         # stop the auto-started BGutil server

# Show what the Truth Agent has learned
ytagent truth show

# List all 10 download methods
ytagent list-methods

# Run the end-to-end self-test
ytagent self-test --mode quick

# Version
ytagent --version
```

## Options

```bash
ytagent download <url> \
  --out-dir /path/to/save     # default: ./downloads
  --format "best[ext=mp4]"    # override yt-dlp format string
  --proxy http://host:port    # route through a proxy (e.g. Cloudflare WARP)
  --timeout 180               # per-method timeout in seconds
  --json                      # print result as JSON (for AI agents)
```

## For AI agents (machine-readable output)

```bash
ytagent download <url> --json
```

Returns a JSON object with `ok`, `video_id`, `final_path`, `method_used`, `attempts[]`, and `total_duration_ms`. Perfect for programmatic consumption.

## Proof of work

A real 243 MB, 213-second, AV1/Opus MP4 was downloaded from an Alibaba HK datacenter IP (`47.57.232.232`) that YouTube blocks with `LOGIN_REQUIRED`. The `android_vr` client + BGutil PO token bypassed the block. The Verifier confirmed all 6 checks passed. See [`docs/proof-of-work/`](docs/proof-of-work/) for artifacts.

## Requirements

- Python 3.11+
- `ffmpeg` and `ffprobe` on PATH (for merging >720p and verifying files)
- `node` and `npm` on PATH (for the BGutil POT provider — auto-installed on first run)
- `git` on PATH (for the BGutil clone — auto-run on first run)

On Ubuntu/Debian: `apt install ffmpeg nodejs npm git`

## Documentation (for developers and AI agents working on ytagent itself)

| File | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Master orientation — read this first if you're modifying ytagent |
| [`agents.md`](agents.md) | Perfection-based role prompts for Orchestrator / Verifier / Truth / Tester |
| [`techstack.md`](techstack.md) | Every dependency, why it's here, upgrade policy |
| [`phases.md`](phases.md) | 6-phase build plan |
| [`plan.md`](plan.md) | Checkable master plan with risk register |
| [`skills.md`](skills.md) | Skill-based prompting reference |
| [`docs/proof-of-work/`](docs/proof-of-work/) | Artifacts from a real end-to-end download |

## License

MIT. See [`LICENSE`](LICENSE).

## Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — the download engine
- [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) — PO token generation that makes datacenter-IP downloads possible
- [Cobalt](https://github.com/imputnet/cobalt), [Piped](https://github.com/TeamPiped/Piped), [Invidious](https://github.com/iv-org/invidious) — alternative download paths in the fallback chain
