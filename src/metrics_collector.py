import threading
import time
from collections import deque
from typing import Dict, Any, List, Tuple

class MetricsCollector:
    """Thread‑safe collector for stick tracking metrics.

    Stores a rolling history (default 5 seconds) of positions, speeds,
    accelerations, strike counts and zone hits. Provides a JSON‑serialisable
    dict via ``to_dict`` for the Flask endpoint.
    """

    def __init__(self, history_seconds: float = 5.0, fps: int = 30):
        self.history_len = int(history_seconds * fps)
        self.lock = threading.Lock()
        # Deques store tuples per frame: (timestamp, left_pos, right_pos)
        self.positions: deque[Tuple[float, Tuple[float, float] | None, Tuple[float, float] | None]] = deque(maxlen=self.history_len)
        # Speed & acceleration history (same length)
        self.speeds: deque[Tuple[float, float, float]] = deque(maxlen=self.history_len)  # (ts, left_speed, right_speed)
        self.accels: deque[Tuple[float, float, float]] = deque(maxlen=self.history_len)
        # Strike data
        self.strikes: List[Dict[str, Any]] = []
        self.strike_counts = {'L': 0, 'R': 0}
        # Zone hit histogram — keys match ZoneHighlighter.get_zone_name
        self.zone_hits = {'center': 0, 'inner': 0, 'outer': 0, 'rim': 0}
        # BPM calculation (based on recent strike timestamps)
        self.recent_strike_ts: deque[float] = deque(maxlen=8)
        # Latest derived values for quick UI consumption
        self.latest: Dict[str, Any] = {}

    def push_frame(self, ts: float, left: Tuple[float, float] | None, right: Tuple[float, float] | None):
        """Record a new frame.

        * ``left`` / ``right`` are (x, y) or ``None`` when not detected.
        """
        with self.lock:
            self.positions.append((ts, left, right))
            # Compute speeds based on previous position
            if len(self.positions) >= 2:
                _, pl, pr = self.positions[-2]
                _, cl, cr = self.positions[-1]
                def _speed(p_prev, p_cur):
                    if p_prev is None or p_cur is None:
                        return 0.0
                    dx = p_cur[0] - p_prev[0]
                    dy = p_cur[1] - p_prev[1]
                    dt = ts - self.positions[-2][0]
                    if dt == 0:
                        return 0.0
                    return ((dx ** 2 + dy ** 2) ** 0.5) / dt
                ls = _speed(pl, cl)
                rs = _speed(pr, cr)
                self.speeds.append((ts, ls, rs))
                # Acceleration from previous speed
                if len(self.speeds) >= 2:
                    _, pls, prs = self.speeds[-2]
                    _, cls, crs = self.speeds[-1]
                    dt = ts - self.speeds[-2][0]
                    la = (cls - pls) / dt if dt else 0.0
                    ra = (crs - prs) / dt if dt else 0.0
                    self.accels.append((ts, la, ra))
            # Update latest scalar metrics for UI
            self.latest.update({
                'timestamp': ts,
                'left_pos': left,
                'right_pos': right,
                'left_speed': self.speeds[-1][1] if self.speeds else 0.0,
                'right_speed': self.speeds[-1][2] if self.speeds else 0.0,
                'left_acc': self.accels[-1][1] if self.accels else 0.0,
                'right_acc': self.accels[-1][2] if self.accels else 0.0,
                'strike_counts': self.strike_counts.copy(),
                'zone_hits': self.zone_hits.copy(),
                'bpm': self._compute_bpm(),
                'recent_strikes': list(self.strikes[-10:])
            })

    def add_strike(self, strike: Dict[str, Any]):
        """Record a new strike.

        ``strike`` must contain ``stick`` ("L"/"R"), ``x``, ``y`` and optional
        ``zone`` name.
        """
        with self.lock:
            self.strikes.append(strike)
            stick = strike.get('stick')
            if stick in self.strike_counts:
                self.strike_counts[stick] += 1
            # Zone histogram update
            zone = strike.get('zone')
            if zone in self.zone_hits:
                self.zone_hits[zone] += 1
            # BPM timestamps
            self.recent_strike_ts.append(strike.get('timestamp', time.time()))
            # Refresh latest dict
            self.latest['strike_counts'] = self.strike_counts.copy()
            self.latest['zone_hits'] = self.zone_hits.copy()
            self.latest['bpm'] = self._compute_bpm()
            self.latest['recent_strikes'] = list(self.strikes[-10:])

    def _compute_bpm(self) -> float:
        """Estimate BPM from recent strike timestamps.

        Uses the average interval between the last few strikes.
        """
        if len(self.recent_strike_ts) < 2:
            return 0.0
        intervals = [self.recent_strike_ts[i] - self.recent_strike_ts[i - 1] for i in range(1, len(self.recent_strike_ts))]
        avg_interval = sum(intervals) / len(intervals)
        return 60.0 / avg_interval if avg_interval > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON‑serialisable snapshot of current metrics."""
        with self.lock:
            return dict(self.latest)
