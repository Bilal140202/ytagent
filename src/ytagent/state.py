"""Atomic state I/O for truth.json and observations.jsonl.

Two persistence primitives:
  - atomic_write_json(path, data)   — write JSON atomically via os.replace
  - atomic_read_json(path, default) — read JSON, return default if missing/corrupt

Both never raise on IO errors. They log and return defaults instead.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import log


def now_iso() -> str:
    """Return current UTC time as ISO8601 string with milliseconds."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def atomic_write_json(path: Path, data: dict[str, Any]) -> bool:
    """Write `data` as JSON to `path` atomically.

    Writes to a temp file in the same directory, then os.replace's it into
    place. This is atomic on POSIX. Returns True on success, False on failure.
    Never raises.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Use same directory so os.replace is atomic (same filesystem).
        fd, tmp_path = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            log.error("atomic_write_json failed", path=str(path), error=str(e))
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False
    except Exception as e:
        log.error("atomic_write_json setup failed", path=str(path), error=str(e))
        return False


def atomic_read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Read JSON from `path`. Return `default` if missing or corrupt. Never raises."""
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warn("atomic_read_json: corrupt or unreadable, using default",
                 path=str(path), error=str(e))
        return default


def append_jsonl(path: Path, record: dict[str, Any]) -> bool:
    """Append `record` as one JSONL line to `path`. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log.error("append_jsonl failed", path=str(path), error=str(e))
        return False
