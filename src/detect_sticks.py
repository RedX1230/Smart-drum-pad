import sys
import os
# Add the project root to sys.path to allow running this script directly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2
import numpy as np
import yaml
import time
from src.camera_overhead import OverheadCamera
from src.kalman_tracker import StickTrackerManager

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")

# HSV thresholds for red and blue stick tips
LOWER_RED1 = np.array([0, 120, 70])
UPPER_RED1 = np.array([10, 255, 255])
LOWER_RED2 = np.array([170, 120, 70])
UPPER_RED2 = np.array([180, 255, 255])
LOWER_BLUE = np.array([90, 80, 70])
UPPER_BLUE = np.array([140, 255, 255])


def load_calibration():
    """Loads pad calibration parameters from config.yaml."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
            if config:
                cal = config.get("calibration", {})
                return (
                    cal.get("center_x", 320),
                    cal.get("center_y", 240),
                    cal.get("radius", 150),
                    cal.get("rim_width", 25)
                )
    except Exception as e:
        print(f"Error loading calibration from config: {e}")
    return 320, 240, 150, 25

def detect_stick_tips(frame, cx, cy, R, debug=False):
    """
    Detect red and blue stick tip candidates inside the calibrated pad region.
    Returns a list of (x, y, color) tuples where color is 'R' for red and 'B' for blue.
    If `debug` is True, color masks are displayed for troubleshooting.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Restrict detection to the pad region
    pad_mask = np.zeros_like(gray)
    cv2.circle(pad_mask, (cx, cy), R, 255, -1)

    red_mask = cv2.inRange(hsv, LOWER_RED1, UPPER_RED1)
    red_mask2 = cv2.inRange(hsv, LOWER_RED2, UPPER_RED2)
    red_mask = cv2.bitwise_or(red_mask, red_mask2)
    blue_mask = cv2.inRange(hsv, LOWER_BLUE, UPPER_BLUE)

    red_mask = cv2.bitwise_and(red_mask, pad_mask)
    blue_mask = cv2.bitwise_and(blue_mask, pad_mask)

    kernel = np.ones((3, 3), np.uint8)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)
    blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_OPEN, kernel)
    blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_CLOSE, kernel)

    tips = []

    def extract_tips(color_mask, color_label):
        contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        best = max(contours, key=cv2.contourArea)
        if cv2.contourArea(best) < 20:
            return None
        pts = best.reshape(-1, 2)
        dists = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
        tip_idx = np.argmax(dists)
        return int(pts[tip_idx, 0]), int(pts[tip_idx, 1]), color_label

    red_tip = extract_tips(red_mask, 'R')
    blue_tip = extract_tips(blue_mask, 'B')
    if red_tip is not None:
        tips.append(red_tip)
    if blue_tip is not None:
        tips.append(blue_tip)

    if debug:
        cv2.imshow("Red Mask", red_mask)
        cv2.imshow("Blue Mask", blue_mask)
        cv2.waitKey(1)

    # If no colored tips are found, fall back to generic dark-tip detection.
    if not tips:
        # Mask to pad area and find dark blobs as a fallback
        masked_gray = cv2.bitwise_and(gray, pad_mask)
        _, thresh = cv2.threshold(masked_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        thresh = cv2.dilate(thresh, kernel, iterations=1)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < 5 or area > 2000:
                continue
            pts = c.reshape(-1, 2)
            dists_to_center = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
            entry_idx = np.argmax(dists_to_center)
            p_entry = pts[entry_idx]
            dists_to_entry = np.hypot(pts[:, 0] - p_entry[0], pts[:, 1] - p_entry[1])
            tip_idx = np.argmax(dists_to_entry)
            p_tip = pts[tip_idx]
            bx, by = int(p_tip[0]), int(p_tip[1])
            bgr = frame[by, bx]
            color = 'B' if bgr[0] > bgr[2] else 'R'
            tips.append((bx, by, color))

    return tips

def main():
    """Main visualization loop for stick tracking."""
    print("Starting visual stick tracker demo...")
    cx, cy, R, rim_width = load_calibration()
    
    cam = OverheadCamera()
    if not cam.start():
        print("Failed to start camera. Exiting.")
        return

    # Initialize tracker manager
    tracker_manager = StickTrackerManager(cx, cy)
    
    print("Press 'q' in the camera window to quit.")
    
    # Keep track of previous coordinates to draw trails
    trail_l = []
    trail_r = []

    while True:
        frame, ts = cam.read()
        if frame is None:
            time.sleep(0.01)
            continue

        # Detect raw candidate tips with color information
        raw_tips = detect_stick_tips(frame, cx, cy, R)
        
        # Update trackers (now expects (x, y, color) tuples)
        tracks = tracker_manager.update(raw_tips)

        # Draw pad calibration guides
        cv2.circle(frame, (cx, cy), R, (255, 255, 255), 1)
        cv2.circle(frame, (cx, cy), R + rim_width, (100, 100, 100), 1)
        cv2.drawMarker(frame, (cx, cy), (100, 100, 100), cv2.MARKER_CROSS, 8, 1)

        # Draw raw detections as colored dots
        for rx, ry, rcolor in raw_tips:
            color = (0, 0, 255) if rcolor == 'R' else (255, 0, 0)
            cv2.circle(frame, (rx, ry), 4, color, -1)

        # Draw Left Tracker (Green)
        if 'L' in tracks:
            lx, ly, lvx, lvy = tracks['L']
            cv2.circle(frame, (int(lx), int(ly)), 8, (0, 255, 0), 2)
            cv2.putText(frame, "L", (int(lx) - 15, int(ly) - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            # Add to trail
            trail_l.append((int(lx), int(ly)))
            if len(trail_l) > 15:
                trail_l.pop(0)

        # Draw Right Tracker (Red)
        if 'R' in tracks:
            rx, ry, rvx, rvy = tracks['R']
            cv2.circle(frame, (int(rx), int(ry)), 8, (0, 0, 255), 2)
            cv2.putText(frame, "R", (int(rx) + 10, int(ry) - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            # Add to trail
            trail_r.append((int(rx), int(ry)))
            if len(trail_r) > 15:
                trail_r.pop(0)

        # Draw trails
        for i in range(1, len(trail_l)):
            cv2.line(frame, trail_l[i-1], trail_l[i], (0, 255, 0), 1)
        for i in range(1, len(trail_r)):
            cv2.line(frame, trail_r[i-1], trail_r[i], (0, 0, 255), 1)

        cv2.imshow("Stick Tracking System", frame)
        
        if cv2.waitKey(10) & 0xFF == ord('q'):
            break

    cam.stop()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
