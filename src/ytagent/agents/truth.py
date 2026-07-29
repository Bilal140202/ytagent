"""Truth Agent — knows which download methods have historically worked.

Owns state/truth.json (ranked method list) and state/observations.jsonl
(append-only audit log). See agents.md Agent 2 for the full spec.

Key behaviors:
  - ranked_methods() returns method names in try-order, best-first.
  - record_observation() appends to observations.jsonl and updates in-memory
    counters. After 3 consecutive failures, demotes by rank += 1 (cap 9).
    A success resets consecutive_failures and may promote by rank -= 1
    (floor 0).
  - Atomic writes via state.atomic_write_json.
  - Never loses an observation. Never raises.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .. import log, state
from ..state import now_iso

# The static baseline chain from CLAUDE.md §4. Used when truth.json
# does not exist yet, or as a fallback if the file is corrupt.
DEFAULT_METHODS = [
    "transcript_probe",
    "ytdlp_default",
    "ytdlp_jsless",
    "ytdlp_ios",
    "ytdlp_single_file",
    "ytdlp_audio_only",
    "innertube_direct",
    "cobalt",
    "piped",
    "invidious",
]

DEMOTION_THRESHOLD = 3      # consecutive failures before demotion
MAX_RANK = 9                # bottom of the chain
MIN_RANK = 0                # top


@dataclass
class Observation:
    """One observation about a method attempt. Appended to observations.jsonl."""

    ts: str
    video_id: str
    method: str
    ok: bool
    reason: str | None
    bytes: int
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TruthAgent:
    """Reads/writes state/truth.json and appends to state/observations.jsonl."""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.truth_path = self.state_dir / "truth.json"
        self.observations_path = self.state_dir / "observations.jsonl"
        self._truth: dict[str, Any] | None = None
        self._load()

    def _load(self) -> None:
        """Load truth.json into memory, writing a default if missing."""
        default = self._default_truth()
        self._truth = state.atomic_read_json(self.truth_path, default)
        # Ensure all known methods are present (in case we added new ones).
        known = {m["name"]: m for m in self._truth.get("methods", [])}
        changed = False
        for i, name in enumerate(DEFAULT_METHODS):
            if name not in known:
                self._truth.setdefault("methods", []).append({
                    "name": name,
                    "rank": i,
                    "consecutive_failures": 0,
                    "success_ratio": 0.0,
                    "attempts": 0,
                })
                changed = True
        if changed or not self._truth.get("updated_at"):
            self._truth["updated_at"] = now_iso()
            state.atomic_write_json(self.truth_path, self._truth)

    def _default_truth(self) -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": now_iso(),
            "methods": [
                {
                    "name": name,
                    "rank": i,
                    "consecutive_failures": 0,
                    "success_ratio": 0.0,
                    "attempts": 0,
                }
                for i, name in enumerate(DEFAULT_METHODS)
            ],
        }

    def ranked_methods(self) -> list[str]:
        """Return method names in the order they should be tried, best-first.

        Sorts by (rank asc, then by success_ratio desc as a tiebreaker).
        Skips methods not in DEFAULT_METHODS (unknown methods).
        """
        if self._truth is None:
            self._load()
        assert self._truth is not None
        methods = self._truth.get("methods", [])
        # Filter to known methods only.
        known = [m for m in methods if m["name"] in DEFAULT_METHODS]
        # Sort by rank asc, then success_ratio desc.
        known.sort(key=lambda m: (m["rank"], -m.get("success_ratio", 0)))
        return [m["name"] for m in known]

    def record_observation(self, obs: Observation) -> None:
        """Append observation to JSONL and update in-memory counters.

        After DEMOTION_THRESHOLD consecutive failures, demote (rank += 1).
        On success, reset consecutive_failures and promote (rank -= 1) if
        the method was demoted previously.
        """
        # Append to JSONL first (never lose the observation).
        state.append_jsonl(self.observations_path, obs.to_dict())

        if self._truth is None:
            self._load()
        assert self._truth is not None

        for m in self._truth.get("methods", []):
            if m["name"] != obs.method:
                continue
            m["attempts"] = m.get("attempts", 0) + 1
            if obs.ok:
                m["consecutive_failures"] = 0
                # Promote if not already at top.
                if m["rank"] > MIN_RANK:
                    # Only promote if there's been sustained success
                    # (at least 1 success and ratio > 0.5).
                    succ = sum(1 for _ in range(m["attempts"]))  # placeholder
                    # Recompute ratio.
                    ratio = m.get("success_ratio", 0.0)
                    new_ratio = (ratio * (m["attempts"] - 1) + 1.0) / m["attempts"]
                    m["success_ratio"] = new_ratio
                    if new_ratio > 0.5 and m["rank"] > MIN_RANK:
                        m["rank"] = max(MIN_RANK, m["rank"] - 1)
            else:
                m["consecutive_failures"] = m.get("consecutive_failures", 0) + 1
                # Update ratio.
                ratio = m.get("success_ratio", 0.0)
                new_ratio = (ratio * (m["attempts"] - 1)) / m["attempts"]
                m["success_ratio"] = new_ratio
                if m["consecutive_failures"] >= DEMOTION_THRESHOLD:
                    if m["rank"] < MAX_RANK:
                        m["rank"] = min(MAX_RANK, m["rank"] + 1)
                        log.warn("Truth demoted method",
                                 method=m["name"],
                                 new_rank=m["rank"],
                                 consecutive_failures=m["consecutive_failures"])
                    m["consecutive_failures"] = 0  # reset after demotion
            break

        self._truth["updated_at"] = now_iso()
        state.atomic_write_json(self.truth_path, self._truth)

    def snapshot(self) -> dict[str, Any]:
        """Return the current truth.json content (for `ytagent truth show`)."""
        if self._truth is None:
            self._load()
        assert self._truth is not None
        return self._truth

    def reset(self, method: str | None = None) -> None:
        """Reset truth.json to defaults. If `method` given, reset only that method."""
        if method is None:
            self._truth = self._default_truth()
        else:
            if self._truth is None:
                self._load()
            assert self._truth is not None
            for m in self._truth.get("methods", []):
                if m["name"] == method:
                    i = DEFAULT_METHODS.index(method) if method in DEFAULT_METHODS else 9
                    m["rank"] = i
                    m["consecutive_failures"] = 0
                    m["success_ratio"] = 0.0
                    m["attempts"] = 0
                    break
        self._truth["updated_at"] = now_iso()
        state.atomic_write_json(self.truth_path, self._truth)
