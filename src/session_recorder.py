"""Persistent store for completed practice sessions.

The rich per-session metrics (accuracy, timing, streak) are computed in the
browser while a phrase is paced against the chosen tempo, so the frontend
POSTs a finished summary here at the end of each run. Sessions are appended
to a single JSON file under ``outputs/`` and read back for the History view.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

# Only these keys are stored, so a malformed or oversized payload can't bloat
# the file. Everything is coerced to a plain JSON-safe scalar.
_ALLOWED = {
    "pattern": str, "bpm": float, "duration_s": float, "strikes": int,
    "accuracy": float, "clean": int, "total": int,
    "mean_ms": float, "spread_ms": float, "best_streak": int,
    "left": int, "right": int, "wrong_hand": int, "missed": int, "extra": int,
    "perfect": int, "good": int, "okay": int,
}


class SessionRecorder:
    """Append-only JSON log of practice sessions (newest kept, capped)."""

    def __init__(self, path: str | os.PathLike | None = None, max_sessions: int = 300):
        base = Path(__file__).resolve().parent.parent
        self.path = Path(path) if path else base / "outputs" / "sessions.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_sessions = max_sessions
        self._lock = threading.Lock()

    def _load(self) -> List[Dict[str, Any]]:
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, ValueError):
            return []

    def _clean(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, cast in _ALLOWED.items():
            if key in raw and raw[key] is not None:
                try:
                    out[key] = cast(raw[key])
                    if cast is str:
                        out[key] = out[key][:60]
                except (TypeError, ValueError):
                    continue
        return out

    def add(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """Validate, timestamp and persist one session; returns the stored record."""
        record = self._clean(session)
        record["recorded_at"] = time.time()
        with self._lock:
            data = self._load()
            data.append(record)
            data = data[-self.max_sessions:]
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(data, fp)
            os.replace(tmp, self.path)
        return record

    def all(self) -> List[Dict[str, Any]]:
        """Every stored session, newest first."""
        with self._lock:
            return list(reversed(self._load()))

    def clear(self) -> None:
        """Remove all stored sessions."""
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
