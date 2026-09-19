"""Game dashboard for a Guitar‑Hero‑style drum practice UI.

This module provides a scrolling note‑lane overlay on the live camera feed,
handles timing‑window classification, keeps a running score/combo, and
persists session results to ``outputs/scores.csv``.

Usage (in ``src/main.py``)::

    from src.game_dashboard import GameDashboard
    dashboard = GameDashboard(chart_path="charts/demo.json")
    # inside the main loop:
    frame = dashboard.update(frame, timestamp, strikes)
    cv2.imshow(..., frame)

When the user quits (``q`` key), call ``dashboard.finalize()`` to write the
CSV entry.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Note:
    """A single drum‑hit cue.

    Attributes
    ----------
    time: float
        Absolute time (seconds) from the start of the session.
    zone: str
        Zone name returned by ``ZoneHighlighter.get_zone_name``.
    hand: str
        ``"L"`` or ``"R"``.
    hit: bool
        Whether the note has already been matched to a strike.
    """

    time: float
    zone: str
    hand: str
    hit: bool = False

    def __lt__(self, other: "Note") -> bool:
        return self.time < other.time

# ---------------------------------------------------------------------------
# Scoring engine – default timing windows
# ---------------------------------------------------------------------------

DEFAULT_WINDOWS = {
    "perfect": 0.030,  # ±30 ms
    "good": 0.070,     # ±70 ms
    "okay": 0.120,     # ±120 ms
}

POINTS = {
    "perfect": 100,
    "good": 70,
    "okay": 40,
    "bad": 0,
}


class ScoringEngine:
    """Classify a strike against the next pending note.

    The engine assumes notes are ordered by time and that only the *first*
    un‑hit note is a candidate for a given hand/zone.  If a strike falls
    outside the ``okay`` window it is counted as ``bad``.
    """

    def __init__(self, windows: Dict[str, float] | None = None):
        self.windows = windows or DEFAULT_WINDOWS
        self.reset()

    def reset(self) -> None:
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.counters = {"perfect": 0, "good": 0, "okay": 0, "bad": 0}

    def classify(self, delta: float) -> str:
        """Return the classification name for a time difference ``delta``.

        ``delta`` is ``abs(strike_time - note_time)``.
        """
        if delta <= self.windows["perfect"]:
            return "perfect"
        if delta <= self.windows["good"]:
            return "good"
        if delta <= self.windows["okay"]:
            return "okay"
        return "bad"

    def record(self, classification: str) -> None:
        self.counters[classification] += 1
        self.score += POINTS[classification]
        if classification != "bad":
            self.combo += 1
            self.max_combo = max(self.max_combo, self.combo)
        else:
            self.combo = 0

# ---------------------------------------------------------------------------
# Dashboard – visual overlay and orchestration
# ---------------------------------------------------------------------------

class GameDashboard:
    """Render a scrolling note lane and keep score.

    Parameters
    ----------
    chart_path: str | Path
        Path to a JSON chart (list of ``{"time", "zone", "hand"}``).
    visible_seconds: float, optional
        How many seconds of future notes are shown on screen (default 3 s).
    speed_px_per_sec: int, optional
        Vertical scrolling speed – pixels travelled per second.
    """

    def __init__(self, chart_path: str | Path, visible_seconds: float = 3.0, speed_px_per_sec: int = 200):
        self.chart_path = Path(chart_path)
        self.visible_seconds = visible_seconds
        self.speed = speed_px_per_sec
        self.notes: List[Note] = []
        self._load_chart()
        self.engine = ScoringEngine()
        self.start_time: float | None = None
        # Output directory for CSV scores
        self.output_dir = Path("outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.score_path = self.output_dir / "scores.csv"
        # UI constants
        self.hit_line_y_ratio = 0.85  # relative to frame height
        self.note_radius = 12
        self.colors = {"L": (0, 255, 0), "R": (0, 0, 255)}
        self.text_color = (255, 255, 255)

    # ---------------------------------------------------------------------
    # Chart handling
    # ---------------------------------------------------------------------
    def _load_chart(self) -> None:
        if not self.chart_path.exists():
            raise FileNotFoundError(f"Chart file not found: {self.chart_path}")
        with open(self.chart_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.notes = [Note(time=n["time"], zone=n["zone"], hand=n["hand"].upper()) for n in raw]
        self.notes.sort()
        self.next_index = 0  # index of the first not‑hit note

    # ---------------------------------------------------------------------
    # Public API – called each frame
    # ---------------------------------------------------------------------
    def update(self, frame: np.ndarray, timestamp: float, strikes: List[Dict[str, Any]]) -> np.ndarray:
        """Overlay notes, process strikes, and return the modified frame.

        ``timestamp`` is the absolute time returned by the camera thread.
        ``strikes`` is the list produced by ``AudioStrikeDetector.update``.
        """
        if self.start_time is None:
            self.start_time = timestamp
        elapsed = timestamp - self.start_time

        # ---------------------------------------------------------------
        # 1️⃣  Render scrolling notes
        # ---------------------------------------------------------------
        h, w = frame.shape[:2]
        hit_line_y = int(h * self.hit_line_y_ratio)
        # Clean up notes that are far past the hit line to keep the list short
        while self.next_index < len(self.notes) and self.notes[self.next_index].time < elapsed - self.visible_seconds:
            self.next_index += 1

        # Draw each note that falls within the visible window
        for note in self.notes[self.next_index :]:
            if note.time - elapsed > self.visible_seconds:
                break
            # Y position: notes start above the hit line and travel downwards
            y = int(hit_line_y - (note.time - elapsed) * self.speed)
            x = self._zone_to_x(note.zone, w)
            color = self.colors.get(note.hand, (200, 200, 200))
            cv2.circle(frame, (x, y), self.note_radius, color, -1)
            if note.hit:
                # Dim the note once it has been hit
                cv2.circle(frame, (x, y), self.note_radius, (50, 50, 50), 2)

        # ---------------------------------------------------------------
        # 2️⃣  Process live strikes against pending notes
        # ---------------------------------------------------------------
        for strike in strikes:
            # ``strike`` dict contains: timestamp, stick, x, y, peak_db, label
            # Find the earliest pending note for the same hand
            candidate = self._next_candidate(strike["stick"], strike["label"])
            if candidate is None:
                # No pending note – count as Bad
                self.engine.record("bad")
                continue
            delta = abs(strike["timestamp"] - (self.start_time + candidate.time))
            classification = self.engine.classify(delta)
            self.engine.record(classification)
            candidate.hit = True
            # Visual feedback – draw a short flash at the hit line
            self._draw_feedback(frame, strike["stick"], classification, hit_line_y, w)

        # ---------------------------------------------------------------
        # 3️⃣  Render score/combo overlay
        # ---------------------------------------------------------------
        self._draw_score(frame)
        return frame

    # ---------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------
    def _zone_to_x(self, zone: str, frame_width: int) -> int:
        """Map a zone name to an X coordinate.

        The pad is circular; we simply distribute zones evenly across the
        horizontal axis for the visual cue.
        """
        mapping = {
            "center": frame_width // 2,
            "inner": int(frame_width * 0.35),
            "outer": int(frame_width * 0.65),
            "rim": int(frame_width * 0.85),
        }
        return mapping.get(zone, frame_width // 2)

    def _next_candidate(self, hand: str, label: str) -> Note | None:
        """Return the first pending note that matches *hand* and *label*.

        ``label`` is the accent classification ("rimshot", "accent", "normal",
        "ghost").  For rimshots the zone check is performed later via the
        note's stored zone.
        """
        for note in self.notes[self.next_index :]:
            if note.hit:
                continue
            if note.hand != hand:
                continue
            # Zone match – for rimshots we require the note zone to be "rim"
            # For other hits we accept any zone (the user may aim anywhere).
            if label == "rimshot" and note.zone != "rim":
                continue
            return note
        return None

    def _draw_feedback(self, frame: np.ndarray, hand: str, classification: str, y: int, w: int) -> None:
        """Draw a brief flash near the hit line to indicate the result."""
        color_map = {
            "perfect": (0, 255, 0),
            "good": (0, 255, 255),
            "okay": (0, 165, 255),
            "bad": (0, 0, 255),
        }
        cx = self._zone_to_x("center", w)
        cx = cx if hand == "L" else w - cx
        cv2.circle(frame, (cx, y), 20, color_map[classification], 3)
        cv2.putText(
            frame,
            classification.upper(),
            (cx - 30, y - 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color_map[classification],
            2,
        )

    def _draw_score(self, frame: np.ndarray) -> None:
        """Overlay the current score, combo and hit counts on the frame."""
        lines = [
            f"Score: {self.engine.score}",
            f"Combo: {self.engine.combo}",
            f"Perfect: {self.engine.counters['perfect']}",
            f"Good: {self.engine.counters['good']}",
            f"Okay: {self.engine.counters['okay']}",
            f"Bad: {self.engine.counters['bad']}",
        ]
        for i, txt in enumerate(lines):
            cv2.putText(
                frame,
                txt,
                (10, 30 + i * 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                self.text_color,
                2,
            )

    # ---------------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------------
    def finalize(self) -> None:
        """Write a CSV row with the session results.

        The CSV has columns: ``timestamp,score,perfect,good,okay,bad,max_combo``.
        ``timestamp`` is the ISO‑8601 UTC time when the session ended.
        """
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        row = [
            now_iso,
            str(self.engine.score),
            str(self.engine.counters["perfect"]),
            str(self.engine.counters["good"]),
            str(self.engine.counters["okay"]),
            str(self.engine.counters["bad"]),
            str(self.engine.max_combo),
        ]
        header = ["timestamp", "score", "perfect", "good", "okay", "bad", "max_combo"]
        file_exists = self.score_path.exists()
        with open(self.score_path, "a", encoding="utf-8") as fp:
            if not file_exists:
                fp.write(",".join(header) + "\n")
            fp.write(",".join(row) + "\n")

# End of GameDashboard implementation
