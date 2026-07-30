"""Structured logger — JSONL to stderr + rich-formatted summary to stdout.

Every log line carries: ts, level, trace_id, msg, plus any extra fields.
The trace_id ties all log lines for a single download() call together.

This module never raises. Logging failures are silently swallowed — the
system must not crash because the logger is broken.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from rich.console import Console
    from rich.panel import Panel
    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False

_console = Console() if _RICH_AVAILABLE else None
_lock = threading.Lock()


def new_trace_id() -> str:
    """Return a short unique trace ID for tying log lines together."""
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _emit(level: str, msg: str, trace_id: str | None, fields: dict[str, Any]) -> None:
    """Emit one structured log line. JSONL to stderr, rich summary to stderr too.

    Both streams go to stderr so stdout is reserved for machine-readable
    output (e.g. `ytagent download --json`).
    """
    record = {
        "ts": _now_iso(),
        "level": level,
        "trace_id": trace_id or "-",
        "msg": msg,
        **fields,
    }
    with _lock:
        try:
            sys.stderr.write(json.dumps(record, default=str) + "\n")
            sys.stderr.flush()
        except Exception:
            pass  # never raise from logging

        if _console is not None and level in {"INFO", "WARN", "ERROR", "SUCCESS"}:
            try:
                style = {
                    "INFO": "cyan",
                    "WARN": "yellow",
                    "ERROR": "red",
                    "SUCCESS": "green",
                }.get(level, "white")
                extra = ""
                if fields:
                    bits = [f"{k}={v}" for k, v in fields.items() if k != "skill"]
                    if bits:
                        extra = "  " + " ".join(bits[:4])
                _console.print(f"[{style}][{level}][/{style}] {msg}[dim]{extra}[/dim]", file=sys.stderr)
            except Exception:
                pass


def info(msg: str, *, trace_id: str | None = None, **fields: Any) -> None:
    _emit("INFO", msg, trace_id, fields)


def warn(msg: str, *, trace_id: str | None = None, **fields: Any) -> None:
    _emit("WARN", msg, trace_id, fields)


def error(msg: str, *, trace_id: str | None = None, **fields: Any) -> None:
    _emit("ERROR", msg, trace_id, fields)


def success(msg: str, *, trace_id: str | None = None, **fields: Any) -> None:
    _emit("SUCCESS", msg, trace_id, fields)


def debug(msg: str, *, trace_id: str | None = None, **fields: Any) -> None:
    """Debug goes to stderr JSONL only (no rich stdout) unless YTAGENT_DEBUG=1."""
    if _emit is None:
        return
    record = {
        "ts": _now_iso(),
        "level": "DEBUG",
        "trace_id": trace_id or "-",
        "msg": msg,
        **fields,
    }
    with _lock:
        try:
            sys.stderr.write(json.dumps(record, default=str) + "\n")
            sys.stderr.flush()
        except Exception:
            pass


def panel(text: str, *, title: str = "", style: str = "cyan") -> None:
    """Print a rich panel to stderr (human-facing summary; stdout reserved for JSON)."""
    if _console is None:
        sys.stderr.write(f"--- {title} ---\n{text}\n--- end ---\n")
        return
    _console.print(Panel(text, title=title, border_style=style), file=sys.stderr)


def write_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append a record as a JSONL line. Creates parent dirs. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass
