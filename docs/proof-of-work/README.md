# Proof of Work — ytagent end-to-end download

This directory contains artifacts proving that `ytagent` successfully downloads
a real YouTube video end-to-end, from a cloud/datacenter environment, with no
cookies and no browser.

## What was tested

- **Date:** 2026-07-29
- **Environment:** Alibaba Cloud HK datacenter (IP `47.57.232.232`, Hong Kong)
- **Constraint:** This IP is on YouTube's datacenter blocklist — direct
  `yt-dlp` returns `LOGIN_REQUIRED: Sign in to confirm you're not a bot` for
  every client (`web`, `android`, `ios`, `tv`, `tv_downgraded`, `mweb`,
  `web_embedded`, `visionos`, `android_vr`).
- **Video:** `dQw4w9WgXcQ` (Rick Astley — Never Gonna Give You Up, public)

## What happened

The `ytagent` orchestrator walked its fallback chain:

1. **Tier 0 — `transcript_probe`**: Passed (738 ms). Video is reachable.
2. **Tier 1 — `ytdlp_default`**: **Succeeded.** This method uses:
   - The `android_vr` innertube client (JS-less — no n-param deciphering needed)
   - The BGutil POT provider (script-node mode, using `node` to generate
     Proof-of-Origin tokens via BotGuard attestation)
   - The PO token is sent with the player API call, which lifts the
     `LOGIN_REQUIRED` block that datacenter IPs normally trigger.
   - Downloaded in 5.5 seconds.

The Verifier then ran all 6 checks on the downloaded file:

| Check | Result |
|---|---|
| 1. Existence & size ≥ 1 MB | ✅ 243,743,156 bytes |
| 2. Magic bytes | ✅ MP4 (`ftyp` box present) |
| 3. ffprobe probe | ✅ exit 0, valid JSON |
| 4. Duration > 0 | ✅ 213.061 seconds |
| 5. Video/audio stream present | ✅ video=av1, audio=opus |
| 6. moov atom sanity | ✅ present and well-formed |

The file was atomically moved to `downloads/proof/dQw4w9WgXcQ.mp4`.

## Artifacts

| File | Description |
|---|---|
| `sample-run.json` | The full `DownloadResult` JSON from the orchestrator, including every attempt with timestamps, durations, and byte counts. |
| `verify-result.json` | The `VerifyResult` JSON from the Verifier, including container, codecs, duration, and size. |
| `../../downloads/proof/dQw4w9WgXcQ.mp4` | The actual downloaded video file (243 MB, not committed to git — see `.gitignore`). Run `ytagent download https://www.youtube.com/watch?v=dQw4w9WgXcQ` to reproduce. |

## How to reproduce

```bash
# 1. Install ytagent
pip install -e .

# 2. Set up the BGutil POT provider (one-time)
git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /home/z/bgutil-ytdlp-pot-provider
cd /home/z/bgutil-ytdlp-pot-provider/server
npm install --production
npm install typescript
./node_modules/.bin/tsc
# (Optional) Start the HTTP server for faster token generation:
nohup node build/main.js --port 4416 > /tmp/bgutil-server.log 2>&1 &

# 3. Download any public YouTube video
ytagent download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

## Why this works (the technical breakthrough)

YouTube blocks datacenter IPs at the **playability level** — the `/youtubei/v1/player`
API call returns `LOGIN_REQUIRED` before any stream URLs are returned. This affects
every innertube client (`web`, `android`, `ios`, `tv`, `mweb`, etc.) when the
request comes from a flagged IP.

The BGutil POT provider generates a **Proof-of-Origin token** by running
Google's BotGuard attestation in Node.js. This token proves to YouTube that
the request comes from a "real" client (not a bot), which lifts the
`LOGIN_REQUIRED` block at the player API level.

Combined with the `android_vr` client (which is JS-less — it doesn't require
n-param signature deciphering), this gives a complete, no-cookie, no-browser
download path from any IP, including datacenter IPs.

The `ytagent` system encapsulates this entire flow behind a single command:
`ytagent download <url>`. The orchestrator tries the BGutil-enabled methods
first, and falls back to 9 other methods if those fail.
