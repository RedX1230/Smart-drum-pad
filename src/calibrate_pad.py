import cv2
import numpy as np
import yaml
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")

def load_config():
    """Load configuration from config.yaml."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
            return config if config is not None else {}
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def save_config(config):
    """Save configuration back to config.yaml."""
    try:
        with open(CONFIG_PATH, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False)
        print("Configuration saved successfully.")
    except Exception as e:
        print(f"Error saving config: {e}")

def detect_pad_circle(frame):
    """
    Robustly detects the white circular drum pad in the frame.
    Uses Otsu's adaptive binarization + circularity shape filtering + Hough Circles fallback.
    Returns (cx, cy, radius) if detected, otherwise None.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Smooth to suppress high-frequency noise/texture
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)

    # 1. Try Otsu's thresholding (severs the bright white skin from dark rim/background)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Morphological opening and closing to clean up borders and interior holes
    kernel = np.ones((5, 5), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_circle = None
    max_area = 0

    for c in contours:
        area = cv2.contourArea(c)
        if area < 3000: # Minimum size threshold
            continue

        perimeter = cv2.arcLength(c, True)
        if perimeter == 0:
            continue

        # Circularity score: 4 * pi * area / (perimeter^2) -> 1.0 for perfect circle
        circularity = 4 * np.pi * area / (perimeter * perimeter)
        
        # Accept reasonably circular shapes (detecting the white pad surface)
        if circularity > 0.65:
            if area > max_area:
                (x, y), radius = cv2.minEnclosingCircle(c)
                best_circle = (int(x), int(y), int(radius))
                max_area = area

    if best_circle is not None:
        return best_circle

    # 2. Fallback: Hough Circle Transform (useful if contrast is low but circular boundaries are present)
    circles = cv2.HoughCircles(
        blurred, 
        cv2.HOUGH_GRADIENT, 
        dp=1.2, 
        minDist=100, 
        param1=50, 
        param2=35, 
        minRadius=50, 
        maxRadius=250
    )
    if circles is not None:
        circles = np.uint16(np.around(circles))
        cx, cy, r = circles[0][0]
        return int(cx), int(cy), int(r)

    return None


def run_pad_calibration():
    """Starts the interactive pad calibration utility."""
    config = load_config()
    cam_cfg = config.get("camera", {})
    cam_idx = cam_cfg.get("index", 0)
    width = cam_cfg.get("width", 640)
    height = cam_cfg.get("height", 480)

    # Calibration defaults or previous values
    cal_cfg = config.get("calibration", {})
    cx = cal_cfg.get("center_x", 320)
    cy = cal_cfg.get("center_y", 240)
    R = cal_cfg.get("radius", 150)
    rim_width = cal_cfg.get("rim_width", 25)

    cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"Failed to open camera index {cam_idx} with DirectShow. Trying default CAP...")
        cap = cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            print("Error: Could not open camera.")
            return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    print("=== Interactive Pad Calibration Mode ===")
    print("Controls:")
    print("  [d]           : Auto-detect circular pad")
    print("  [i]/[k]/[j]/[l] or Arrow keys : Move center Up/Down/Left/Right")
    print("  [w]/[s]       : Increase/Decrease pad radius")
    print("  [e]/[c]       : Increase/Decrease rim width")
    print("  [Enter] / [S] : Save calibration settings and exit")
    print("  [Esc] / [q]   : Quit without saving")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to capture frame from camera.")
            break

        # Flip horizontally for mirrored feel
        frame = cv2.flip(frame, 1)
        display_frame = frame.copy()

        # Retrieve zone settings
        zones_cfg = config.get("zones", {"inner": 0.2, "middle": 0.5, "outer": 0.8})
        inner_r = int(zones_cfg.get("inner", 0.2) * R)
        middle_r = int(zones_cfg.get("middle", 0.5) * R)
        outer_r = int(zones_cfg.get("outer", 0.8) * R)

        # Draw visual guides on display_frame
        # Center marker
        cv2.drawMarker(display_frame, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 12, 1)
        # Concentric zones
        cv2.circle(display_frame, (cx, cy), inner_r, (100, 100, 100), 1)
        cv2.circle(display_frame, (cx, cy), middle_r, (100, 150, 100), 1)
        cv2.circle(display_frame, (cx, cy), outer_r, (150, 100, 100), 1)
        # Pad border (yellow)
        cv2.circle(display_frame, (cx, cy), R, (0, 255, 255), 2)
        # Outer rim border (red)
        cv2.circle(display_frame, (cx, cy), R + rim_width, (0, 0, 255), 2)

        # On-screen text
        cv2.putText(display_frame, f"Pad Center: ({cx}, {cy})", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(display_frame, f"Radius R: {R}", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(display_frame, f"Rim Width: {rim_width}", (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(display_frame, "Press Enter/S to Save, Q/Esc to Quit", (10, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        cv2.imshow("Smart Drum Pad Calibration", display_frame)

        key = cv2.waitKey(1)
        
        # Check standard key codes and common virtual key codes
        if key == 27 or key == ord('q') or key == ord('Q'):
            print("Calibration canceled.")
            break
        elif key == 13 or key == ord('s') or key == ord('S'):
            if "calibration" not in config:
                config["calibration"] = {}
            config["calibration"]["center_x"] = cx
            config["calibration"]["center_y"] = cy
            config["calibration"]["radius"] = R
            config["calibration"]["rim_width"] = rim_width
            save_config(config)
            break
        elif key == ord('d') or key == ord('D'):
            detection = detect_pad_circle(frame)
            if detection is not None:
                cx, cy, R = detection
                print(f"Auto-detected circle: cx={cx}, cy={cy}, R={R}")
            else:
                print("Could not auto-detect white circular pad. Center and adjust lighting.")
        
        # Center adjustments
        elif key == ord('i') or key == ord('I') or key == 82: # Up
            cy -= 1
        elif key == ord('k') or key == ord('K') or key == 84: # Down
            cy += 1
        elif key == ord('j') or key == ord('J') or key == 81: # Left
            cx -= 1
        elif key == ord('l') or key == ord('L') or key == 83: # Right
            cx += 1
            
        # Radius adjustments
        elif key == ord('w') or key == ord('W'):
            R += 1
        elif key == ord('s') or key == ord('S'):
            R = max(5, R - 1)
            
        # Rim adjustments
        elif key == ord('e') or key == ord('E'):
            rim_width += 1
        elif key == ord('c') or key == ord('C'):
            rim_width = max(0, rim_width - 1)

    cap.release()
    cv2.destroyAllWindows()

def calibrate_latency():
    """Placeholder for latency calibration."""
    print("=== Audio-Visual Latency Calibration ===")
    print("This feature will synchronize audio transient events with visual strike frames.")
    print("It will be implemented in a later phase once the audio engine is fully set up.")

if __name__ == "__main__":
    run_pad_calibration()
