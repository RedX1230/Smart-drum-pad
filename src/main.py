import sys
import os
import time
import math
import argparse

# Ensure project root is on sys.path for direct script execution
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2
from src.accent_detection import augment_strike
from src.game_dashboard import GameDashboard

from src.camera_overhead import OverheadCamera
from src.detect_sticks import load_calibration, detect_stick_tips
from src.kalman_tracker import StickTrackerManager
from src.calibrate_pad import run_pad_calibration, load_config
from src.zone_simulation import run_zone_simulation
from src.detect_strikes import AudioStrikeDetector
from src.zone_highlighter import ZoneHighlighter
from src.metrics_collector import MetricsCollector
from src.web_dashboard import start_web_server, ingest_strike

# Global metrics collector instance
collector = MetricsCollector()
# Start Flask server in background daemon thread
start_web_server(collector)


def ask_yes_no(prompt, default='y'):
    ans = input(f"{prompt} [{'Y/n' if default=='y' else 'y/N'}]: ").strip().lower()
    if ans == '':
        ans = default
    return ans in ('y', 'yes')


def main():
    parser = argparse.ArgumentParser(description="Smart Drum Pad main runner")
    parser.add_argument("--no-calib", action="store_true", help="Skip interactive pad calibration")
    parser.add_argument("--debug", action="store_true", help="Show color mask debug windows")
    parser.add_argument("--cam", type=int, default=None, help="Camera index override")
    parser.add_argument("--web-only", action="store_true",
                        help="Run only the web UI (no camera/desktop window); practise with the keyboard")
    args = parser.parse_args()

    print("Smart Drum Pad — Main")

    if args.web_only:
        print("Web UI running at http://127.0.0.1:5000  (Ctrl+C to stop)")
        print("No detector — use the page to build patterns, review history and calibrate.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
        return

    # Optionally run interactive pad calibration
    if not args.no_calib:
        if ask_yes_no("Run pad calibration now?", default='y'):
            run_pad_calibration()

    # Load calibration (center, radius, rim)
    cx, cy, R, rim_width = load_calibration()

    debug = args.debug or ask_yes_no("Show color mask debug windows?", default='n')

    show_zones = ask_yes_no("Show zone simulation?", default='n')

    if show_zones:
        run_zone_simulation(cam_idx=args.cam, show_mask=debug)
        return

    cam = OverheadCamera()
    if args.cam is not None:
        cam.camera_idx = args.cam
    if not cam.start():
        print("Failed to start camera. Exiting.")
        return

    tracker_manager = StickTrackerManager(cx, cy)

    # Build the audio detector from config.yaml so the Setup screen's values
    # are the ones actually in effect. ``threshold`` is a linear 0–1 amplitude.
    audio_cfg = (load_config() or {}).get('audio', {})
    sample_rate = int(audio_cfg.get('sample_rate') or 44100)
    device_index = audio_cfg.get('device_index')
    thr = audio_cfg.get('threshold')
    threshold_db = 20.0 * math.log10(max(float(thr), 1e-4)) if thr else -20.0
    strike_detector = AudioStrikeDetector(
        sample_rate=sample_rate, threshold_db=threshold_db,
        cooldown_ms=120, device=device_index,
    )
    zone_highlighter = ZoneHighlighter(cx, cy, R, rim_width)

    # Initialize the game dashboard (scrolling note lane)
    dashboard = GameDashboard(chart_path="charts/demo.json")

    trail_l = []
    trail_r = []

    print("Press 'q' to quit, 'd' to toggle debug masks.")
    print("[AUDIO] Listening for drum strikes on microphone...")
    show_debug = debug

    try:
        while True:
            frame, ts = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue

            tips = detect_stick_tips(frame, cx, cy, R, debug=show_debug)
            tracks = tracker_manager.update(tips)
            # Push metrics for this frame
            left_pos = tracks.get('L')[:2] if 'L' in tracks else None
            right_pos = tracks.get('R')[:2] if 'R' in tracks else None
            collector.push_frame(ts, left_pos, right_pos)
            
            # Detect strikes using audio and tracking
            strikes = strike_detector.update(tracks, ts)
            for strike in strikes:
                zone_name = zone_highlighter.get_zone_name(int(strike['x']), int(strike['y']))
                augment_strike(strike, zone_name)
                strike['zone'] = zone_name
                # Single in-process ingestion: metrics collector + pattern evaluator
                ingest_strike(strike)
            # Update the scrolling dashboard (adds notes, scores, etc.)
            frame = dashboard.update(frame, ts, strikes)

            # Draw pad guides
            cv2.circle(frame, (cx, cy), R, (255, 255, 255), 1)
            cv2.circle(frame, (cx, cy), R + rim_width, (100, 100, 100), 1)
            cv2.drawMarker(frame, (cx, cy), (100, 100, 100), cv2.MARKER_CROSS, 8, 1)

            # Draw raw detections
            for t in tips:
                if len(t) == 3:
                    rx, ry, rcol = t
                    color = (0, 0, 255) if rcol == 'R' else (255, 0, 0)
                    cv2.circle(frame, (rx, ry), 4, color, -1)

            # Draw Left Tracker (Green)
            if 'L' in tracks:
                lx, ly, lvx, lvy = tracks['L']
                cv2.circle(frame, (int(lx), int(ly)), 8, (0, 255, 0), 2)
                cv2.putText(frame, "L", (int(lx) - 15, int(ly) - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                trail_l.append((int(lx), int(ly)))
                if len(trail_l) > 15:
                    trail_l.pop(0)

            # Draw Right Tracker (Red)
            if 'R' in tracks:
                rx, ry, rvx, rvy = tracks['R']
                cv2.circle(frame, (int(rx), int(ry)), 8, (0, 0, 255), 2)
                cv2.putText(frame, "R", (int(rx) + 10, int(ry) - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                trail_r.append((int(rx), int(ry)))
                if len(trail_r) > 15:
                    trail_r.pop(0)

            # Draw trails
            for i in range(1, len(trail_l)):
                cv2.line(frame, trail_l[i - 1], trail_l[i], (0, 255, 0), 1)
            for i in range(1, len(trail_r)):
                cv2.line(frame, trail_r[i - 1], trail_r[i], (0, 0, 255), 1)

            # Draw detected strikes

            cv2.imshow("Smart Drum Pad - Tracking", frame)

            key = cv2.waitKey(10) & 0xFF
            if key == ord('q'):
                break
            if key == ord('d'):
                show_debug = not show_debug

    finally:
        # Finalize dashboard (persist scores)
        dashboard.finalize()
        strike_detector.stop()
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
