import sys
import os
import cv2
import numpy as np

# Ensure project root on sys.path when executed directly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.camera_overhead import OverheadCamera
from src.detect_sticks import load_calibration


# DRUM TIP COLOR (red) thresholds (HSV)
LOWER_RED1 = np.array([0, 60, 60])
UPPER_RED1 = np.array([10, 200, 200])
LOWER_RED2 = np.array([170, 60, 60])
UPPER_RED2 = np.array([180, 200, 200])


def detect_drum(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)

    kernel = np.ones((5, 5), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 3000:
        return None

    (x, y), radius = cv2.minEnclosingCircle(c)
    return int(x), int(y), int(radius)


def draw_zones(frame, cx, cy, R):
    cv2.circle(frame, (cx, cy), int(0.2 * R), (100, 100, 100), 1)
    cv2.circle(frame, (cx, cy), int(0.5 * R), (100, 100, 100), 1)
    cv2.circle(frame, (cx, cy), int(0.8 * R), (100, 100, 100), 1)
    cv2.circle(frame, (cx, cy), R, (0, 255, 255), 2)


def detect_tip(frame, cx, cy, R):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    mask1 = cv2.inRange(hsv, LOWER_RED1, UPPER_RED1)
    mask2 = cv2.inRange(hsv, LOWER_RED2, UPPER_RED2)
    mask = cv2.bitwise_or(mask1, mask2)

    # restrict to drum area
    drum_mask = np.zeros_like(mask)
    cv2.circle(drum_mask, (cx, cy), R, 255, -1)
    mask = cv2.bitwise_and(mask, drum_mask)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, mask

    contours = [c for c in contours if cv2.contourArea(c) > 120]
    if not contours:
        return None, mask

    c = max(contours, key=cv2.contourArea)
    tip = tuple(c[c[:, :, 1].argmax()][0])
    return (tip, c), mask


def run_zone_simulation(cam_idx=None, show_mask=True):
    """Runs the zone simulation using the threaded OverheadCamera.
    Returns when user quits.
    """
    cx, cy, R, _ = load_calibration()

    cam = OverheadCamera()
    if cam_idx is not None:
        cam.camera_idx = cam_idx
    if not cam.start():
        print("Failed to start camera for zone simulation.")
        return

    drum_locked = False
    prev_tip = None

    try:
        while True:
            frame, ts = cam.read()
            if frame is None:
                cv2.waitKey(1)
                continue

            # OverheadCamera already mirrors the frame; no second flip here.
            if not drum_locked:
                result = detect_drum(frame)
                if result is not None:
                    cx, cy, R = result
                    drum_locked = True
                    print("Drum locked")

            if drum_locked:
                draw_zones(frame, cx, cy, R)

                result, mask = detect_tip(frame, cx, cy, R)
                if show_mask:
                    cv2.imshow("Zone Mask", mask)

                if result is not None:
                    (x, y), contour = result
                    if prev_tip is not None:
                        px, py = prev_tip
                        x = int(0.7 * px + 0.3 * x)
                        y = int(0.7 * py + 0.3 * y)
                    prev_tip = (x, y)
                    cv2.drawContours(frame, [contour], -1, (255, 0, 0), 2)
                    cv2.circle(frame, (x, y), 6, (0, 255, 0), -1)

            cv2.imshow("Zone Simulation", frame)
            key = cv2.waitKey(10) & 0xFF
            if key == ord('q') or key == 27:
                break
            if key == ord('r'):
                drum_locked = False
                prev_tip = None

    finally:
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    run_zone_simulation()