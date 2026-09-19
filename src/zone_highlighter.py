import os

import cv2
import numpy as np
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")

ZONE_COLORS = {
    'center': (0, 255, 0),   # bright green
    'inner': (0, 255, 255),  # yellow
    'outer': (0, 0, 255),    # red
    'rim': (255, 0, 0),      # blue
}

DEFAULT_ZONE_RATIOS = {
    'inner': 0.2,
    'middle': 0.5,
    'outer': 0.8,
}


def load_zone_ratios():
    """Load zone ratio settings from config.yaml, or return defaults."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f) or {}
            return config.get('zones', DEFAULT_ZONE_RATIOS)
    except Exception:
        return DEFAULT_ZONE_RATIOS


class ZoneHighlighter:
    """
    Visual zone highlighting for Smart Drum Pad strikes.

    The class keeps active zone hits alive for a short duration and renders
    them as semi-transparent overlays that fade over time.
    """

    def __init__(self, cx, cy, R, rim_width, zone_ratios=None, active_ms=200):
        self.cx = int(cx)
        self.cy = int(cy)
        self.R = int(R)
        self.rim_width = int(rim_width)
        self.active_ms = active_ms

        ratios = zone_ratios if zone_ratios is not None else load_zone_ratios()
        self.inner_r = int(ratios.get('inner', DEFAULT_ZONE_RATIOS['inner']) * self.R)
        self.middle_r = int(ratios.get('middle', DEFAULT_ZONE_RATIOS['middle']) * self.R)
        self.outer_r = int(ratios.get('outer', DEFAULT_ZONE_RATIOS['outer']) * self.R)

        self.active_hits = []  # [{'zone': name, 'timestamp': ts}]

    def register_hit(self, zone_name, timestamp):
        if zone_name is None:
            return
        self.active_hits.append({'zone': zone_name, 'timestamp': timestamp})

    def update(self, timestamp):
        self.active_hits = [hit for hit in self.active_hits if (timestamp - hit['timestamp']) * 1000.0 <= self.active_ms]

    def get_zone_name(self, x, y):
        dx = x - self.cx
        dy = y - self.cy
        dist = np.hypot(dx, dy)

        if dist <= self.inner_r:
            return 'center'
        if dist <= self.middle_r:
            return 'inner'
        if dist <= self.outer_r:
            return 'outer'
        if dist <= self.R + self.rim_width:
            return 'rim'
        return None

    def _zone_mask(self, zone_name, frame_shape):
        mask = np.zeros(frame_shape[:2], dtype=np.uint8)
        if zone_name == 'center':
            cv2.circle(mask, (self.cx, self.cy), self.inner_r, 255, -1)
        elif zone_name == 'inner':
            cv2.circle(mask, (self.cx, self.cy), self.middle_r, 255, -1)
            cv2.circle(mask, (self.cx, self.cy), self.inner_r, 0, -1)
        elif zone_name == 'outer':
            cv2.circle(mask, (self.cx, self.cy), self.outer_r, 255, -1)
            cv2.circle(mask, (self.cx, self.cy), self.middle_r, 0, -1)
        elif zone_name == 'rim':
            cv2.circle(mask, (self.cx, self.cy), self.R + self.rim_width, 255, -1)
            cv2.circle(mask, (self.cx, self.cy), self.outer_r, 0, -1)
        return mask

    def _blend_overlay(self, frame, mask, color, alpha):
        overlay = np.zeros_like(frame, dtype=np.uint8)
        overlay[mask == 255] = color
        alpha_mask = (mask == 255)
        if not np.any(alpha_mask):
            return

        # Blend only the masked pixels
        frame_float = frame.astype(np.float32)
        overlay_float = overlay.astype(np.float32)
        frame[alpha_mask] = np.clip(
            (1.0 - alpha) * frame_float[alpha_mask] + alpha * overlay_float[alpha_mask],
            0,
            255,
        ).astype(np.uint8)

    def draw(self, frame):
        now = cv2.getTickCount() / cv2.getTickFrequency()
        self.update(now)

        for hit in self.active_hits:
            age_ms = (now - hit['timestamp']) * 1000.0
            fade = max(0.0, 1.0 - age_ms / self.active_ms)
            if fade == 0.0:
                continue

            zone_name = hit['zone']
            color = ZONE_COLORS.get(zone_name, (255, 255, 255))
            mask = self._zone_mask(zone_name, frame.shape)
            self._blend_overlay(frame, mask, color, fade * 0.5)

        # Draw outline rings for reference
        cv2.circle(frame, (self.cx, self.cy), self.inner_r, (100, 100, 100), 1)
        cv2.circle(frame, (self.cx, self.cy), self.middle_r, (100, 100, 100), 1)
        cv2.circle(frame, (self.cx, self.cy), self.outer_r, (100, 100, 100), 1)
        cv2.circle(frame, (self.cx, self.cy), self.R + self.rim_width, (100, 100, 100), 1)

    def __len__(self):
        return len(self.active_hits)
