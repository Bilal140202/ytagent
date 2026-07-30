# plan.md — The Master Plan for `ytagent`

> A linear, checkable execution plan derived from `phases.md`. This is the file to live-update as work progresses. When a box is checked, the work is done and verified.

**Last updated:** 2026-07-30
**Current phase:** Phase 1 — Scaffolding (in flight)

---

## Phase 0 — Research & Documentation ✅

- [x] Spawn 3 parallel research agents (yt-dlp internals, multi-agent patterns, Innertube API)
- [x] Aggregate findings into `/home/z/my-project/worklog.md`
- [x] Author `CLAUDE.md` (master orientation)
- [x] Author `agents.md` (perfection-based role prompts)
- [x] Author `techstack.md` (every dep + why + cost + upgrade policy)
- [x] Author `phases.md` (6-phase build plan)
- [x] Author `plan.md` (this file)
- [x] Author `skills.md` (skill-based prompting reference)

## Phase 1 — Scaffolding (in flight)

- [x] Create directory tree per `CLAUDE.md` §2
- [ ] Write `pyproject.toml` with all deps from `techstack.md` §2
- [ ] Implement `src/ytagent/__init__.py` with `__version__`
- [ ] Implement `src/ytagent/log.py` (structured JSONL + rich summary)
- [ ] Implement `src/ytagent/state.py` (atomic truth.json + observations.jsonl)
- [ ] Implement `src/ytagent/utils/ids.py` (`to_video_id` URL parser)
- [ ] Implement `src/ytagent/utils/net.py` (shared `requests.Session` + retries)
- [ ] Implement `src/ytagent/utils/ff.py` (ffmpeg/ffprobe wrappers)
- [ ] Implement `src/ytagent/cli.py` (click entry: `--version`, `--help`, stub subcommands)
- [ ] `pip install -e .` succeeds
- [ ] `ytagent --version` prints `ytagent 0.1.0`
- [ ] `ruff check .` clean
- [ ] Commit Phase 1

## Phase 2 — The Four Agents (mocked methods)

- [ ] Generate test fixtures via `scripts/make_fixtures.py` (valid_5s.mp4, truncated.mp4, not_a_video.txt)
- [ ] Implement `src/ytagent/agents/verifier.py` (6-check pipeline)
- [ ] Implement `src/ytagent/agents/truth.py` (ranked_methods + record_observation + atomic writes)
- [ ] Implement `src/ytagent/orchestrator.py` (walk chain, hand to Verifier, atomic move on success)
- [ ] Implement `src/ytagent/agents/tester.py` (--quick / --full modes)
- [ ] Write `tests/test_verifier.py` (one test per check + combo)
- [ ] Write `tests/test_truth.py` (ranking, demote/promote, atomic write)
- [ ] Write `tests/test_orchestrator.py` (FakeMethod that succeeds/fails/raises)
- [ ] Write `tests/test_ids.py` (every URL shape)
- [ ] `pytest tests/ -x --cov=ytagent --cov-fail-under=85` passes
- [ ] Commit Phase 2

## Phase 3 — Method Backends

### 3.0 Method base interface
- [ ] Implement `src/ytagent/methods/base.py` (`MethodResult` dataclass + `Method` protocol)
- [ ] Implement `src/ytagent/methods/__init__.py` (`METHOD_REGISTRY`)

### 3.1 Tier 0 — transcript probe
- [ ] `src/ytagent/methods/transcript_probe.py`
- [ ] Unit test (mocked HTTP)

### 3.2 Tier 1 — yt-dlp default chain
- [ ] `src/ytagent/methods/ytdlp_default.py`
- [ ] Unit test (mocked `YoutubeDL`)

### 3.3 Tier 1b — yt-dlp JS-less only
- [ ] `src/ytagent/methods/ytdlp_jsless.py`
- [ ] Unit test

### 3.4 Tier 2 — yt-dlp IOS client
- [ ] `src/ytagent/methods/ytdlp_ios.py`
- [ ] Unit test

### 3.5 Tier 3 — yt-dlp single muxed file
- [ ] `src/ytagent/methods/ytdlp_single_file.py`
- [ ] Unit test

### 3.6 Tier 4 — yt-dlp audio-only salvage
- [ ] `src/ytagent/methods/ytdlp_audio_only.py`
- [ ] Unit test

### 3.7 Tier 5 — direct Innertube API
- [ ] `src/ytagent/methods/innertube_direct.py` (TVHTML5 client + ANDROID sub-fallback)
- [ ] Unit test (mocked `/youtubei/v1/player`)

### 3.8 Tier 6 — Cobalt sidecar
- [ ] `src/ytagent/methods/cobalt.py`
- [ ] Unit test (mocked Cobalt API)
- [ ] Connection-refused handling

### 3.9 Tier 7 — Piped API rotation
- [ ] `src/ytagent/methods/piped.py`
- [ ] Unit test (mocked multi-instance rotation)

### 3.10 Tier 8 — Invidious redirect
- [ ] `src/ytagent/methods/invidious.py`
- [ ] Unit test (mocked redirect)

### 3.11 Wire-up
- [ ] All 10 methods registered in `METHOD_REGISTRY`
- [ ] `ytagent download <real-public-url>` succeeds end-to-end
- [ ] Commit Phase 3

## Phase 4 — End-to-end testing & proof of work

- [ ] Run `ytagent --self-test --quick` — exit 0
- [ ] Run `ytagent --self-test --full` — generate `state/self-test-<ts>.md`
- [ ] Download `BaW_jenozKc` to `downloads/proof/`
- [ ] Capture `docs/proof-of-work/sample-run.jsonl`
- [ ] Capture `docs/proof-of-work/verify-result.json`
- [ ] Write `docs/proof-of-work/README.md`
- [ ] Commit proof-of-work

## Phase 5 — Sidecars (escape hatches, parallel to Phase 4)

- [ ] `docker-compose.sidecars.yml` (BGutil + WARP + Cobalt)
- [ ] `scripts/install_sidecars.sh`
- [ ] CLI flags `--warp`, `--bgutil`, `--cobalt-url`
- [ ] README section on sidecars
- [ ] Commit Phase 5

## Phase 6 — Polish, packaging, ship

- [ ] `README.md` (quickstart, install, usage, examples)
- [ ] `LICENSE` (MIT)
- [ ] `CONTRIBUTING.md`
- [ ] `.gitignore`
- [ ] `scripts/Dockerfile` (agent container)
- [ ] `ytagent truth show` subcommand
- [ ] `ytagent truth reset` subcommand
- [ ] `ytagent --list-methods` subcommand
- [ ] `git tag v0.1.0`
- [ ] Push to GitHub: `github.com/Bilal140202/ytagent`

## Post-ship (out of scope for v0.1.0)

- [ ] PyPI publish
- [ ] Weekly yt-dlp version bump CI job
- [ ] `state/observations.jsonl` rotation
- [ ] Prometheus metrics endpoint
- [ ] Age-restricted video support (requires cookie workflow — separate project)

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| YouTube blocks `visionos`/`android_vr` clients | Medium | High | Tier 5+ fallbacks; WARP sidecar |
| yt-dlp extractor breaks upstream | Medium | High | Pin version; bump on release; Tier 5+ fallbacks |
| Datacenter IP gets "Sign in to confirm you're not a bot" | High | High | WARP sidecar (Phase 5) |
| `ffprobe` not installed | Low | Medium | Magic-byte fallback in Verifier; document in README |
| `python-magic` can't find libmagic | Low | Low | Set `MAGIC_FILE` defensively; fall back to hardcoded byte checks |
| Cobalt/Piped/Invidious instances disappear | High | Low | Multi-instance rotation; demote in Truth after failures |
| `state/observations.jsonl` grows unbounded | Low | Low | Document; future rotation job |
| yt-dlp release breaks our pinned API usage | Low | Medium | Pin version; read yt-dlp changelog before bumping |

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-30 | Use yt-dlp as the primary engine, not a hand-rolled Innertube client | yt-dlp has a JS interpreter, PO Token framework, and 5 years of breakage-fixing. Re-implementing would be hubris. |
| 2026-07-30 | Use `visionos` + `android_vr` as the JS-less default chain | Research confirmed these are PO-token-free and don't require signature deciphering. Fastest path. |
| 2026-07-30 | Deterministic state machine, no LLM at runtime | The system is called by AI agents; it must not itself call an LLM. Determinism = predictability = trust. |
| 2026-07-30 | Truth Agent writes JSON, not SQLite | JSON is git-diffable, human-readable, and atomic via `os.replace`. SQLite is overkill for ~10 method entries. |
| 2026-07-30 | Append-only `observations.jsonl` | Audit trail is sacred. Overwriting loses history. Growth is acceptable for v0.1.0. |
| 2026-07-30 | Verifier checks moov atom placement for MP4 | Truncated MP4 downloads are the most common silent failure mode. Detecting them saves downstream agents from playing broken files. |
| 2026-07-30 | No cookies, no OAuth, ever | Cloud agents have no browser. Public videos only. This is the contract. |
| 2026-07-30 | Fallback chain has 10 tiers, not 3 | YouTube breaks things in surprising ways. More tiers = more resilience. Each tier is cheap to implement. |

— end of plan.md —
