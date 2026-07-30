"""Orchestrator — the main loop.

Receives a target (URL or video ID), walks the fallback chain of methods
in the order given by the Truth Agent, hands each successful result to
the Verifier, and atomically moves the verified file into place on success.

See agents.md Agent 1 for the full contract.

Key invariants:
  - Never raises.
  - Never asks the user a question.
  - Verifier gates every success.
  - Each method gets a clean temp dir.
  - Final file is atomically moved via os.replace.
"""

from __future__ import annotations

import os
import shutil
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import log
from .agents.truth import Observation, TruthAgent
from .agents.verifier import Verifier
from .methods import METHOD_REGISTRY
from .methods.base import MethodResult, default_opts
from .state import now_iso
from .utils.ids import to_video_id


@dataclass
class Attempt:
    """Record of one method attempt within a download()."""

    method: str
    started_at: str
    finished_at: str
    ok: bool
    reason: str | None
    verify_reason: str | None = None
    bytes_downloaded: int = 0
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": self.ok,
            "reason": self.reason,
            "verify_reason": self.verify_reason,
            "bytes_downloaded": self.bytes_downloaded,
            "duration_ms": self.duration_ms,
        }


@dataclass
class DownloadResult:
    """Final result of Orchestrator.download()."""

    ok: bool
    video_id: str
    final_path: str | None = None
    method_used: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    total_duration_ms: int = 0
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "video_id": self.video_id,
            "final_path": self.final_path,
            "method_used": self.method_used,
            "attempts": [a.to_dict() for a in self.attempts],
            "total_duration_ms": self.total_duration_ms,
            "trace_id": self.trace_id,
        }


class _MethodTimeout(Exception):
    """Internal: raised when a method exceeds its timeout."""


def _run_with_timeout(fn: Callable, timeout_s: int) -> MethodResult:
    """Run a method callable with a hard timeout. Returns MethodResult.

    yt-dlp methods can't be cleanly interrupted mid-download, but we can
    at least bound the wait. If the timeout fires, we return a failure
    result. The yt-dlp process may continue in the background for a bit
    but its output file will be ignored.
    """
    result_holder: dict[str, Any] = {"result": None, "exc": None}

    def _target():
        try:
            result_holder["result"] = fn()
        except Exception as e:
            result_holder["exc"] = e

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        # Thread is still running — the method is taking too long.
        return MethodResult(
            ok=False,
            reason=f"method timed out after {timeout_s}s",
            duration_ms=timeout_s * 1000,
        )

    if result_holder["exc"] is not None:
        e = result_holder["exc"]
        return MethodResult(
            ok=False,
            reason=f"method raised: {type(e).__name__}: {e}",
        )

    return result_holder["result"] or MethodResult(ok=False, reason="method returned None")


class Orchestrator:
    """The main download orchestrator. See agents.md Agent 1."""

    def __init__(
        self,
        truth: TruthAgent,
        verifier: Verifier,
        methods: dict[str, Callable] | None = None,
    ):
        self.truth = truth
        self.verifier = verifier
        self.methods = methods if methods is not None else METHOD_REGISTRY

    def download(
        self,
        target: str,
        out_dir: Path,
        opts: dict[str, Any] | None = None,
    ) -> DownloadResult:
        """Walk the fallback chain. Return DownloadResult. Never raises."""
        from .log import new_trace_id
        trace_id = new_trace_id()
        started = time.monotonic()
        opts = opts or default_opts()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Resolve target to a video ID.
        try:
            video_id = to_video_id(target)
        except ValueError as e:
            log.error("Orchestrator: bad target", target=target, error=str(e), trace_id=trace_id)
            return DownloadResult(
                ok=False,
                video_id="",
                trace_id=trace_id,
                total_duration_ms=int((time.monotonic() - started) * 1000),
            )

        log.info("Orchestrator starting download",
                 video_id=video_id, out_dir=str(out_dir), trace_id=trace_id)

        # Get the ranked method list from Truth.
        ranked = self.truth.ranked_methods()
        log.info("Truth ranked methods", methods=ranked, trace_id=trace_id)

        attempts: list[Attempt] = []
        tmp_root = out_dir / ".tmp" / video_id
        tmp_root.mkdir(parents=True, exist_ok=True)

        final_path: str | None = None
        method_used: str | None = None

        for method_name in ranked:
            if method_name not in self.methods:
                log.warn("method in truth.json but not registered; skipping",
                         method=method_name, trace_id=trace_id)
                continue

            method_fn = self.methods[method_name]
            method_tmp_dir = tmp_root / method_name
            method_tmp_dir.mkdir(parents=True, exist_ok=True)

            attempt_started_at = now_iso()
            attempt_started = time.monotonic()

            log.info("trying method", method=method_name, trace_id=trace_id, video_id=video_id)

            # Run the method with a timeout.
            timeout_s = opts.get("timeout", 180)
            try:
                result = _run_with_timeout(
                    lambda fn=method_fn, vid=video_id, d=method_tmp_dir, o=opts: fn(vid, d, o),
                    timeout_s,
                )
            except Exception as e:
                result = MethodResult(
                    ok=False,
                    reason=f"orchestrator caught: {type(e).__name__}: {e}",
                )

            result.method = method_name
            attempt_duration = int((time.monotonic() - attempt_started) * 1000)
            attempt_finished_at = now_iso()

            # Build the Attempt record.
            attempt = Attempt(
                method=method_name,
                started_at=attempt_started_at,
                finished_at=attempt_finished_at,
                ok=False,  # we'll set True only after Verifier passes
                reason=result.reason,
                bytes_downloaded=result.bytes_downloaded,
                duration_ms=attempt_duration,
            )

            if not result.ok:
                log.warn("method failed", method=method_name, reason=result.reason, trace_id=trace_id)
                # Record observation and continue.
                self.truth.record_observation(Observation(
                    ts=now_iso(),
                    video_id=video_id,
                    method=method_name,
                    ok=False,
                    reason=result.reason,
                    bytes=result.bytes_downloaded,
                    duration_ms=attempt_duration,
                ))
                attempts.append(attempt)
                # Clean up the method's temp dir to avoid disk bloat.
                _safe_rmtree(method_tmp_dir)
                continue

            # Method claimed success. Verify.
            if result.path is None:
                # transcript_probe returns ok=True with path=None.
                # This is the preflight; record as success and continue.
                log.info("preflight passed", method=method_name, trace_id=trace_id)
                attempt.ok = True
                attempt.reason = result.reason
                self.truth.record_observation(Observation(
                    ts=now_iso(),
                    video_id=video_id,
                    method=method_name,
                    ok=True,
                    reason=result.reason,
                    bytes=0,
                    duration_ms=attempt_duration,
                ))
                attempts.append(attempt)
                continue

            log.info("method produced file; verifying",
                     method=method_name, path=result.path, trace_id=trace_id)
            verify_result = self.verifier.verify(Path(result.path))

            if verify_result.ok:
                # SUCCESS. Move file to final location.
                ext = Path(result.path).suffix or ".mp4"
                final = out_dir / f"{video_id}{ext}"
                try:
                    # Atomic move within same filesystem.
                    if Path(result.path).resolve() != final.resolve():
                        shutil.move(str(result.path), str(final))
                except Exception as e:
                    log.error("failed to move file to final location",
                              src=result.path, dst=str(final), error=str(e), trace_id=trace_id)
                    attempt.reason = f"move failed: {e}"
                    self.truth.record_observation(Observation(
                        ts=now_iso(),
                        video_id=video_id,
                        method=method_name,
                        ok=False,
                        reason=f"move failed: {e}",
                        bytes=result.bytes_downloaded,
                        duration_ms=attempt_duration,
                    ))
                    attempts.append(attempt)
                    _safe_rmtree(method_tmp_dir)
                    continue

                log.success("download verified and moved to final location",
                            method=method_name, final_path=str(final),
                            duration_s=verify_result.duration_s,
                            size_bytes=verify_result.size_bytes,
                            container=verify_result.container,
                            trace_id=trace_id)

                attempt.ok = True
                attempt.reason = None
                self.truth.record_observation(Observation(
                    ts=now_iso(),
                    video_id=video_id,
                    method=method_name,
                    ok=True,
                    reason=None,
                    bytes=result.bytes_downloaded,
                    duration_ms=attempt_duration,
                ))
                attempts.append(attempt)
                final_path = str(final)
                method_used = method_name
                # Clean up temp dir.
                _safe_rmtree(method_tmp_dir)
                break
            else:
                # Verifier rejected.
                log.warn("verifier rejected method output",
                         method=method_name, reason=verify_result.reason, trace_id=trace_id)
                attempt.verify_reason = verify_result.reason
                self.truth.record_observation(Observation(
                    ts=now_iso(),
                    video_id=video_id,
                    method=method_name,
                    ok=False,
                    reason=f"verify failed: {verify_result.reason}",
                    bytes=result.bytes_downloaded,
                    duration_ms=attempt_duration,
                ))
                attempts.append(attempt)
                # Delete the bad file.
                try:
                    Path(result.path).unlink(missing_ok=True)
                except Exception:
                    pass
                _safe_rmtree(method_tmp_dir)
                continue

        # Clean up the .tmp/<video_id> directory if empty.
        try:
            if tmp_root.exists() and not any(tmp_root.iterdir()):
                tmp_root.rmdir()
                # Also try to remove .tmp if now empty.
                tmp_root.parent.rmdir()
        except Exception:
            pass

        total_duration = int((time.monotonic() - started) * 1000)
        result = DownloadResult(
            ok=final_path is not None,
            video_id=video_id,
            final_path=final_path,
            method_used=method_used,
            attempts=attempts,
            total_duration_ms=total_duration,
            trace_id=trace_id,
        )

        if result.ok:
            log.success("Orchestrator completed",
                        video_id=video_id,
                        method_used=method_used,
                        total_duration_ms=total_duration,
                        trace_id=trace_id)
        else:
            log.error("Orchestrator exhausted all methods",
                      video_id=video_id,
                      attempts_tried=len(attempts),
                      total_duration_ms=total_duration,
                      trace_id=trace_id)

        return result


def _safe_rmtree(path: Path) -> None:
    """Best-effort recursive delete. Never raises."""
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
