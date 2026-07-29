# ytagent — An Agentic YouTube Downloader for Cloud-Based AI Agents

`ytagent` is a deterministic, multi-agent, CLI-first YouTube downloader built
specifically for cloud-based AI agents and headless CLIs. It wraps `yt-dlp`
in a multi-method fallback chain with a Verifier, Truth Agent, and Tester,
and automatically handles the datacenter IP blocks that YouTube imposes.

**One goal:** the calling agent gives us a YouTube URL; we return a path to a
verified, playable video file on disk. Everything else is implementation.

## Quickstart

```bash
# Install
pip install -e .

# Set up the BGutil POT provider (one-time, ~2 minutes)
git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /home/z/bgutil-ytdlp-pot-provider
cd /home/z/bgutil-ytdlp-pot-provider/server
npm install --production && npm install typescript && ./node_modules/.bin/tsc

# (Optional, faster) Start the BGutil HTTP server
nohup node /home/z/bgutil-ytdlp-pot-provider/server/build/main.js --port 4416 &

# Download any public YouTube video
ytagent download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

The downloaded video lands in `downloads/<video_id>.mp4` by default.

## Why this exists

Cloud-based AI agents (like this CLI) cannot:
- Run a browser (no `--cookies-from-browser`)
- Use OAuth (deprecated and removed from yt-dlp)
- Supply cookies (no authenticated session)
- Use a GUI

And when running on datacenter IPs, YouTube blocks them with
"Sign in to confirm you're not a bot" (`LOGIN_REQUIRED`).

`ytagent` solves this by:
1. Using the **`android_vr`** innertube client (JS-less — no n-param deciphering)
2. Auto-loading the **BGutil POT provider** (generates Proof-of-Origin tokens
   via BotGuard attestation in Node.js, which lifts the LOGIN_REQUIRED block)
3. Walking a **10-tier fallback chain** — if one method fails, the next is tried
4. **Verifying** every downloaded file with ffprobe + magic bytes + moov atom checks
5. **Learning** which methods work best in this environment (Truth Agent)

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
│ (truth.json  │    │ (6-layer file    │    │ (10 tiers):      │
│  + obs.jsonl)│    │  integrity check)│    │  ytdlp_default   │
│              │    │                  │    │  ytdlp_jsless    │
│ Ranks        │    │ 1. size ≥ 1MB    │    │  ytdlp_ios       │
│ methods by   │    │ 2. magic bytes   │    │  ytdlp_single    │
│ observed     │    │ 3. ffprobe       │    │  ytdlp_audio     │
│ success      │    │ 4. duration > 0  │    │  innertube_direct│
│              │    │ 5. stream exists │    │  cobalt          │
│              │    │ 6. moov atom     │    │  piped           │
│              │    │                  │    │  invidious       │
└──────────────┘    └──────────────────┘    │  transcript_probe│
                                             └──────────────────┘
```

See `agents.md` for the full perfection-based role prompts for each agent.

## The fallback chain

| Tier | Method | Strategy |
|---|---|---|
| 0 | `transcript_probe` | Preflight reachability check (separate rate-limit bucket) |
| 1 | `ytdlp_default` | `android_vr` client + BGutil PO token (primary path) |
| 1b | `ytdlp_jsless` | `visionos, android_vr` clients + BGutil |
| 2 | `ytdlp_ios` | IOS client (HLS, sometimes dodges blocks) |
| 3 | `ytdlp_single_file` | Pre-muxed MP4 (no ffmpeg merge, fastest) |
| 4 | `ytdlp_audio_only` | Audio-only salvage (last yt-dlp tier) |
| 5 | `innertube_direct` | Hand-rolled POST to `/youtubei/v1/player` |
| 6 | `cobalt` | Self-hosted Cobalt sidecar |
| 7 | `piped` | Piped API with 4-instance rotation |
| 8 | `invidious` | Invidious `latest_version` redirect (360p last resort) |

The Truth Agent ranks these by observed success ratio. After 3 consecutive
failures of a method, it's demoted. After a success, its rank may improve.

## CLI reference

```bash
# Download a video
ytagent download <url-or-id> [--out-dir DIR] [--format FMT] [--proxy URL]

# Show the Truth Agent's learned state
ytagent truth show

# Reset Truth Agent state
ytagent truth reset [--method NAME]

# Run the end-to-end self-test
ytagent self-test --mode quick

# List all registered methods
ytagent list-methods

# Print version
ytagent --version
```

## Documentation

| File | Purpose |
|---|---|
| `CLAUDE.md` | Master orientation for any AI agent working on this repo |
| `agents.md` | Perfection-based role prompts for Orchestrator / Verifier / Truth / Tester |
| `techstack.md` | Every dependency, why it's here, what it costs, upgrade policy |
| `phases.md` | 6-phase build plan with definitions of done |
| `plan.md` | Checkable master plan with risk register and decision log |
| `skills.md` | Skill-based prompting reference (16 skills mapped to code) |
| `docs/proof-of-work/` | Artifacts from a real end-to-end download |

## Constraints (non-negotiable)

1. **No cookies. No OAuth. No browser sessions.** Public videos only.
2. **No GUI. No interactive prompts.** 100% non-interactive CLI.
3. **No LLM at runtime.** Deterministic state machine.
4. **Fallback is mandatory.** Walk the chain on failure.
5. **Verification is mandatory.** Every download passes 6 checks.
6. **Files stay under `/home/z/my-project/`.**

See `CLAUDE.md` §1 for the full constraint list.

## Proof of work

A real 243 MB, 213-second, AV1/Opus MP4 was downloaded from a datacenter IP
(Alibaba HK, `47.57.232.232`) that YouTube blocks with `LOGIN_REQUIRED`.
The `android_vr` client + BGutil PO token bypassed the block. The Verifier
confirmed the file. See `docs/proof-of-work/` for artifacts.

## License

MIT. See `LICENSE`.

## Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — the download engine
- [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) — PO token generation
- [Cobalt](https://github.com/imputnet/cobalt) — alternative download API
- [Piped](https://github.com/TeamPiped/Piped) — federated YouTube frontend
- [Invidious](https://github.com/iv-org/invidious) — privacy-friendly YouTube frontend
