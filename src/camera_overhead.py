import cv2
import threading
import time
import os
import yaml

class OverheadCamera:
    """Threaded camera wrapper for low-latency frame acquisition."""
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")
        
        self.config_path = config_path
        self.camera_idx = 0
        self.width = 640
        self.height = 480
        
        # Load settings from config.yaml
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
                if config:
                    cam_cfg = config.get("camera", {})
                    self.camera_idx = cam_cfg.get("index", 0)
                    self.width = cam_cfg.get("width", 640)
                    self.height = cam_cfg.get("height", 480)
        except Exception as e:
            print(f"Error loading camera config: {e}")
            
        self.cap = None
        self.frame = None
        self.timestamp = 0.0
        self.is_running = False
        self.lock = threading.Lock()
        self.thread = None

    def start(self):
        """Start frame capture in a background thread."""
        if self.is_running:
            return True
            
        # Try DirectShow for low capture latency on Windows, fallback to default CAP
        self.cap = cv2.VideoCapture(self.camera_idx, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.camera_idx)
            
        if not self.cap.isOpened():
            print(f"Failed to open camera index {self.camera_idx}")
            return False
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        
        self.is_running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print(f"Camera stream started on index {self.camera_idx}")
        return True

    def _capture_loop(self):
        """Asynchronous loop reading frames from the camera device."""
        while self.is_running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.001)
                continue
                
            # Flip horizontally for mirrored feedback
            frame = cv2.flip(frame, 1)
            
            with self.lock:
                self.frame = frame
                self.timestamp = time.time()
                
            # Sleep slightly to prevent high CPU utilization
            time.sleep(0.005)

    def read(self):
        """Returns the latest frame (mirrored) and its capture timestamp."""
        with self.lock:
            if self.frame is None:
                return None, 0.0
            return self.frame.copy(), self.timestamp

    def stop(self):
        """Stops the capture thread and releases camera resources."""
        self.is_running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        print("Camera stream stopped.")

if __name__ == "__main__":
    # Test camera feed if run directly
    cam = OverheadCamera()
    if cam.start():
        print("Displaying camera feed for 5 seconds. Press 'q' to quit.")
        start_time = time.time()
        while time.time() - start_time < 5.0:
            frame, ts = cam.read()
            if frame is not None:
                cv2.imshow("Threaded Camera Test", frame)
            if cv2.waitKey(10) & 0xFF == ord('q'):
                break
        cam.stop()
        cv2.destroyAllWindows()
