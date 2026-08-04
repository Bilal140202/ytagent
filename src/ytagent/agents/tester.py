"""Tester agent — runs the system against known-stable public videos.

See agents.md Agent 4 for the full spec. Two modes:
  - quick (default): one corpus video, < 120s.
  - full: all corpus videos, 5s sleep between.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import log
from ..orchestrator import Orchestrator
from ..state import now_iso
from .verifier import Verifier

# Known-stable public YouTube videos for end-to-end smoke tests.
# These are widely-embedded, very stable, public videos suitable for testing.
# Replace with any public video IDs you prefer — these are just defaults.
CORPUS = [
    "BaW_jenozKc",   # public test video
    "aqz-KE-bpKQ",   # public animated short
    "M7lc1UVf-VE",   # public tech talk
]

CORPUS_FULL = CORPUS + [
    "_OBlgSz8sSM",   # public viral video
    "9bZkp7q19f0",   # public music video
]


@dataclass
class TestResult:
    """Result of testing one corpus video."""

    video_id: str
    ok: bool
    method_used: str | None = None
    duration_s: float | None = None
    size_bytes: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "ok": self.ok,
            "method_used": self.method_used,
            "duration_s": self.duration_s,
            "size_bytes": self.size_bytes,
            "reason": self.reason,
        }


@dataclass
class TestReport:
    """Full self-test report."""

    started_at: str
    finished_at: str
    mode: str
    results: list[TestResult] = field(default_factory=list)
    exit_code: int = 1

    def to_markdown(self) -> str:
        """Render the report as a markdown table."""
        lines = [
            f"# ytagent self-test report",
            f"",
            f"- **Mode:** {self.mode}",
            f"- **Started:** {self.started_at}",
            f"- **Finished:** {self.finished_at}",
            f"- **Exit code:** {self.exit_code}",
            f"",
            f"| # | Video ID | OK | Method | Duration (s) | Size (bytes) | Reason |",
            f"|---|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(self.results, 1):
            ok_str = "yes" if r.ok else "no"
            dur = f"{r.duration_s:.1f}" if r.duration_s else "-"
            size = str(r.size_bytes) if r.size_bytes else "-"
            reason = (r.reason or "")[:60].replace("|", "\\|")
            lines.append(
                f"| {i} | {r.video_id} | {ok_str} | {r.method_used or '-'} | {dur} | {size} | {reason} |"
            )
        lines.append("")
        return "\n".join(lines)


class Tester:
    """End-to-end smoke tester. See agents.md Agent 4."""

    def __init__(self, orchestrator: Orchestrator, verifier: Verifier):
        self.orchestrator = orchestrator
        self.verifier = verifier

    def run(
        self,
        mode: str = "quick",
        out_dir: Path | None = None,
        keep_files: bool = False,
    ) -> TestReport:
        """Run the smoke test. Returns a TestReport."""
        started_at = now_iso()
        started = time.monotonic()
        out_dir = Path(out_dir) if out_dir else Path("/home/z/my-project/ytdl-agent/state/self-test")
        out_dir.mkdir(parents=True, exist_ok=True)

        corpus = CORPUS if mode == "quick" else CORPUS_FULL
        results: list[TestResult] = []

        for i, video_id in enumerate(corpus):
            log.info("self-test: running video", video_id=video_id, mode=mode, i=i + 1, total=len(corpus))
            video_out = out_dir / video_id
            video_out.mkdir(parents=True, exist_ok=True)

            dl_result = self.orchestrator.download(video_id, video_out)
            tr = TestResult(
                video_id=video_id,
                ok=dl_result.ok,
                method_used=dl_result.method_used,
                reason=dl_result.attempts[-1].reason if dl_result.attempts and not dl_result.ok else None,
            )
            if dl_result.ok and dl_result.final_path:
                # Verify the final file.
                vr = self.verifier.verify(Path(dl_result.final_path))
                tr.duration_s = vr.duration_s
                tr.size_bytes = vr.size_bytes
                if not vr.ok:
                    tr.ok = False
                    tr.reason = f"verify failed: {vr.reason}"

                if not keep_files:
                    # Clean up the downloaded file.
                    try:
                        Path(dl_result.final_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                    # Clean up the .tmp dir.
                    try:
                        (video_out / ".tmp").rmdir()
                    except Exception:
                        pass

            results.append(tr)

            # Sleep between videos in full mode to avoid rate-limiting.
            if mode == "full" and i < len(corpus) - 1:
                log.info("self-test: sleeping 5s between videos")
                time.sleep(5)

        exit_code = 0 if all(r.ok for r in results) else 1
        finished_at = now_iso()

        report = TestReport(
            started_at=started_at,
            finished_at=finished_at,
            mode=mode,
            results=results,
            exit_code=exit_code,
        )

        # Write the markdown report.
        md_path = out_dir / f"self-test-{started_at.replace(':', '').replace('.', '')}.md"
        try:
            md_path.write_text(report.to_markdown(), encoding="utf-8")
            log.info("self-test report written", path=str(md_path))
        except Exception as e:
            log.error("failed to write self-test report", path=str(md_path), error=str(e))

        elapsed = int((time.monotonic() - started) * 1000)
        log.info("self-test complete",
                 mode=mode, exit_code=exit_code, total_duration_ms=elapsed)

        return report
