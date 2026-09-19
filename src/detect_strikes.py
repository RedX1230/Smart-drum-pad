"""
Audio-triggered strike detection for Smart Drum Pad.

AudioStrikeDetector monitors microphone input for sudden transient peaks
and uses camera-based stick tracking only to determine WHERE the strike occured.

This module treats the microphone as evidence of impact timing and evaluates
Left/Right stick motion independently so that near-simultaneous hits can both
be recorded.
"""

import collections
import numpy as np
import sounddevice as sd
import threading
import time


class AudioStrikeDetector:
    """
    Detects strikes from microphone audio peaks and attributes them to tracked sticks.

    Strike timing comes from audio transients. Each audio impact evaluates Left
    and Right motion independently so one audio peak can produce two strike events.
    """

    def __init__(
        self,
        sample_rate=44100,
        block_size=1024,
        threshold_db=-22.0,
        cooldown_ms=120,
        peak_retrigger_ms=10,
        history_size=8,
        motion_threshold=120.0,
    ):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.threshold_db = threshold_db
        self.cooldown_ms = cooldown_ms
        self.peak_retrigger_ms = peak_retrigger_ms
        self.history_size = history_size
        self.motion_threshold = motion_threshold

        # Convert dB threshold to linear amplitude
        self.threshold_linear = 10 ** (threshold_db / 20.0)

        # Audio buffering: keep ~50ms of samples for low latency
        self.audio_buffer = collections.deque(maxlen=sample_rate // 20)
        self.lock = threading.Lock()

        # Per-stick cooldown state
        self.last_strike_time = {'L': 0.0, 'R': 0.0}
        self.last_audio_peak_time = 0.0

        # Latest stick tracking state and history for motion scoring
        self.last_tracks = {}
        self.track_history = {
            'L': collections.deque(maxlen=history_size),
            'R': collections.deque(maxlen=history_size),
        }

        # Visualization state
        self.strike_markers = {}
        self.frame_count = 0

        self.stream = None
        self.is_running = False
        self._start_stream()

    def _start_stream(self):
        """Start the microphone input stream for low-latency audio detection."""
        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                blocksize=self.block_size,
                callback=self._audio_callback,
                latency='low',
            )
            self.stream.start()
            self.is_running = True
            print(f"[AUDIO] Microphone stream started: {self.sample_rate}Hz, threshold={self.threshold_db}dB")
        except Exception as exc:
            print(f"[AUDIO ERROR] Could not open microphone: {exc}")
            self.is_running = False

    def _audio_callback(self, indata, frames, time_info, status):
        """Non-blocking callback that stores incoming audio samples."""
        if status:
            print(f"[AUDIO WARNING] {status}")

        with self.lock:
            self.audio_buffer.extend(indata[:, 0].tolist())

    def _detect_audio_peak(self):
        """Return True when a transient peak appears above the configured threshold."""
        with self.lock:
            if len(self.audio_buffer) < self.block_size:
                return False

            recent = np.array(self.audio_buffer, dtype=np.float32)[-self.block_size:]
            peak = np.max(np.abs(recent))
            rms = np.sqrt(np.mean(recent ** 2)) if recent.size > 0 else 0.0

        now = time.time()
        if peak <= self.threshold_linear or peak <= max(0.25, 2.5 * rms):
            return False

        if (now - self.last_audio_peak_time) * 1000.0 < self.peak_retrigger_ms:
            return False

        self.last_audio_peak_time = now
        self.last_peak_db = 20.0 * np.log10(max(peak, 1e-6))
        return True

    def _append_track_history(self, tracks, timestamp):
        for stick_id in ['L', 'R']:
            if stick_id in tracks:
                x, y, vx, vy = tracks[stick_id]
                self.track_history[stick_id].append({
                    'ts': timestamp,
                    'x': x,
                    'y': y,
                    'vx': vx,
                    'vy': vy,
                })

    def _motion_metrics(self, stick_id):
        history = self.track_history[stick_id]
        if len(history) < 2:
            return 0.0, 0.0, 0.0, 0.0

        last = history[-1]
        first = history[0]
        dt = max(last['ts'] - first['ts'], 1e-3)

        velocity_mag = np.hypot(last['vx'], last['vy'])
        position_change = np.hypot(last['x'] - first['x'], last['y'] - first['y']) / dt

        acceleration_mag = 0.0
        if len(history) >= 2:
            prev = history[-2]
            dt_prev = max(last['ts'] - prev['ts'], 1e-3)
            acceleration_mag = np.hypot(last['vx'] - prev['vx'], last['vy'] - prev['vy']) / dt_prev

        score = (velocity_mag * 0.55) + (position_change * 0.3) + (acceleration_mag * 0.15)
        return score, velocity_mag, position_change, acceleration_mag

    def _can_generate_strike(self, stick_id, timestamp):
        elapsed_ms = (timestamp - self.last_strike_time[stick_id]) * 1000.0
        return elapsed_ms >= self.cooldown_ms

    def update(self, tracks, timestamp):
        """
        Update the detector with current tracking state and return audio-triggered strikes.

        Args:
            tracks: {'L': (x, y, vx, vy), 'R': (x, y, vx, vy)}
            timestamp: frame timestamp in seconds

        Returns:
            List of strike events: [{'stick': 'L', 'timestamp': ts, 'x': x, 'y': y}, ...]
        """
        self.frame_count += 1
        self.last_tracks = tracks.copy()
        self._append_track_history(tracks, timestamp)

        strikes = []
        if self._detect_audio_peak():
            left_score, left_vel, left_pos, left_acc = self._motion_metrics('L')
            right_score, right_vel, right_pos, right_acc = self._motion_metrics('R')

            print("[AUDIO] Audio peak detected")
            print(f"[AUDIO] Left score: {left_score:.1f} (vel={left_vel:.1f}, pos={left_pos:.1f}, acc={left_acc:.1f})")
            print(f"[AUDIO] Right score: {right_score:.1f} (vel={right_vel:.1f}, pos={right_pos:.1f}, acc={right_acc:.1f})")

            candidates = []
            for stick_id, score in [('L', left_score), ('R', right_score)]:
                if stick_id not in tracks:
                    continue
                if score < self.motion_threshold:
                    continue
                if not self._can_generate_strike(stick_id, timestamp):
                    continue
                candidates.append(stick_id)

            generated = []
            for stick_id in candidates:
                x, y, vx, vy = tracks[stick_id]
                strike_event = {
                    'timestamp': timestamp,
                    'stick': stick_id,
                    'x': x,
                    'y': y,
                    'peak_db': getattr(self, 'last_peak_db', -60.0),
                }
                strikes.append(strike_event)
                self.last_strike_time[stick_id] = timestamp
                self.strike_markers[(stick_id, self.frame_count)] = {'x': int(x), 'y': int(y)}
                generated.append(stick_id)

            if generated:
                print(f"[AUDIO] Generated strikes: {' '.join(generated)}")
            else:
                print("[AUDIO] Generated strikes: none")

        return strikes

    def draw_strikes(self, frame, max_marker_age=15):
        import cv2

        to_remove = []
        for (stick_id, frame_idx), marker in list(self.strike_markers.items()):
            age = self.frame_count - frame_idx
            if age > max_marker_age:
                to_remove.append((stick_id, frame_idx))
                continue

            alpha = 1.0 - age / max_marker_age
            x, y = marker['x'], marker['y']
            cv2.circle(frame, (x, y), 6, (0, 255, 255), 2)
            cv2.putText(frame, f"{stick_id}", (x + 10, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        for key in to_remove:
            del self.strike_markers[key]

    def stop(self):
        """Stop the audio stream cleanly."""
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            self.is_running = False
            print("[AUDIO] Microphone stream stopped.")

    def __del__(self):
        self.stop()
