# Subtitles & the Datacenter Playbook

Field notes from a real cloud run (2026-11-04): a 61-minute foreign-language
radio broadcast on YouTube, fetched from a datacenter IP where every
conventional route was blocked. This document records what failed, what
worked, and the rules the codebase now follows because of it. (Per repo
convention, no specific video names or IDs are recorded here.)

## TL;DR rules

1. **Try the iOS Innertube client early.** A raw `youtubei/v1/player` POST
   with the iOS client context returned `playabilityStatus: OK` — full
   metadata, caption tracks, streaming data — from an IP where yt-dlp was
   bot-walled (`LOGIN_REQUIRED`) and the ANDROID_VR client also returned
   `LOGIN_REQUIRED`.
2. **Metadata + captions are a partial success, not a failure.** When the
   media bytes can't be fetched, `innertube_direct` now attaches the player
   metadata and caption-track list to its result as `extra["salvage"]`.
   For subtitle tasks, that *is* the deliverable.
3. **Fetch captions in the source language; never depend on `tlang`.**
   The caption track's signed `baseUrl` + `&fmt=json3` succeeds from
   datacenter IPs. The same URL with `&tlang=<lang>` (YouTube's own
   translation) is rate-limited much harder (HTTP 429 / connection resets)
   on the same IP, at the same time. Translate locally instead
   (`ytagent subtitles` uses the gtx web endpoint; the translator is
   swappable in `ytagent/captions.py`).
4. **Signed googlevideo URLs are egress-IP-bound across their 302.**
   The redirect target's signature encodes the egress IP of the original
   request. Following the redirect through a proxy with a *different*
   egress yields `HTTP 403` and 0 bytes. Fetch media through the same
   egress that requested the player response.
5. **Fix names before translating, not after.** Machine translation will
   mangle proper nouns, and ASR mishears them in the source language too
   (in the field run, the most-mentioned person's name was misheard by ASR
   as a common noun 17 times vs 1 correct hearing). `ytagent subtitles
   --subs-file` applies source→canonical substitutions to the source text
   before translation. Verify each candidate substitution in context
   first: a substring that looks like a name may be an ordinary word
   ending (a polite verb ending contained the same syllables in 4/4 hits).

## What failed in the field run, and why

| Route | Observed failure |
|---|---|
| yt-dlp (default clients) | HTTP 429 on the watch page, then `Sign in to confirm you're not a bot` (LOGIN_REQUIRED) |
| ytagent tiers 1–6 (yt-dlp variants + innertube as then written) | same bot wall / no usable formats |
| yt-dlp `--extractor-args youtube:player_client=ios` | SABR-only experiment: iOS https formats "skipped as they are missing a URL"; only images downloadable. The **raw** player API still returned URLs — yt-dlp's extraction, not the API, is what SABR defeats here. |
| Cobalt (local sidecar) | nothing listening on `127.0.0.1:9000` — now skipped at preflight by operators; count it as "not configured", not "failed" |
| Cobalt community relays | relay IPs blocked after ~2 calls; remaining instances require JWT |
| Piped (4 instances) | all failed |
| Invidious `local=true` (4 instances) | all failed |
| SOCKS5 farm | no working proxy found in the public lists |
| GitHub Actions farm | never attempted: no token in opts. **Fixed in v0.4.0** — the farm now also reads `YTAGENT_GITHUB_TOKEN` from the environment. |
| Direct googlevideo URLs from the player response | 302 redirect → 403 (egress-IP binding, rule 4 above) |
| Caption `tlang` translation | HTTP 429 / reset on every format (json3, srv3, vtt) |

## What worked

### 1. Raw Innertube player request, iOS client (`ytagent/innertube.py`)

```
POST https://www.youtube.com/youtubei/v1/player?key=<WEB client key>&prettyPrint=false
{
  "context": { "client": {
      "clientName": "IOS", "clientVersion": "20.10.4",
      "deviceMake": "Apple", "deviceModel": "iPhone16,2",
      "osName": "iPhone", "osVersion": "18.3.2.22D82" } },
  "videoId": "<id>",
  "racyCheckOk": true,
  "contentCheckOk": true
}
```

`fetch_player()` tries iOS → ANDROID_VR → TVHTML5 and returns the first
playable response (or the last one, for diagnostics). Note the existing
`methods/innertube_direct.py` keeps its own client table and order for the
*download* path; `innertube.py` is the shared metadata/captions path.

### 2. Source-language captions as json3 (`ytagent/captions.py`)

`GET {captionTracks[i].baseUrl}&fmt=json3` — 2,913 timed events for the
61-minute broadcast, with per-segment offsets. ASR json3 events are single
lines separated by `\n` window events; `parse_json3_lines()` drops the
separators, `segment_lines()` regroups lines into cues (sentence-final
breaks; hard caps 7 s span / 62 chars; pause breaks at 2.5 s).

### 3. Local translation, batched with a sentinel

Cues are translated 10 at a time, joined by a sentinel token
(`ZXQMARKERZXQ`) that survives machine translation; the response is split
back on the sentinel. If a batch comes back with the wrong number of
parts, each cue in it is retried individually. ~880 cues translated in
~4 minutes with zero hard failures in the field run.

### 4. QC that caught real defects

On the delivered SRT: 1,045 cues, no source-language characters left, no
overlapping cues, max cue duration 8.3 s, last cue ends within 2 s of the
video's length, and per-name occurrence counts compared against the
source transcript (this is what exposed the ASR name mishearing in
rule 5 — the name appeared once in a naive pass and 18 times after the
substitution fix).

## Using it

```bash
# English SRT for any captioned video (source track auto-detected)
ytagent subtitles "https://www.youtube.com/watch?v=<id>" --to en

# With name/term protection (JSON object: source form -> canonical form)
ytagent subtitles <url> --to en --subs-file names.json

# Machine-readable summary for agents
ytagent subtitles <url> --to en --json
```

`names.json` example shape (values are whatever canonical forms you need):

```json
{ "source-language name": "CANONICAL NAME", "nickname": "CANONICAL NAME" }
```

## Known limits

- Translation quality is machine translation of ASR: idioms and rapid
  overlapping speech will read awkwardly in places. The timing, however,
  is the broadcaster's own caption timing.
- Ad breaks and songs inside a broadcast are subtitled as aired.
- The iOS player response's media URLs remain subject to rule 4; on
  networks without a proxy-egress mismatch they may download directly.
- Client versions in `innertube.py` age. When iOS starts failing, bump
  `clientVersion`/`osVersion` to a current pairing before trying anything
  more exotic.
