import numpy as np
import time
from filterpy.kalman import KalmanFilter

class StickKalmanTracker:
    """Kalman Filter tracker for a single drumstick tip."""
    def __init__(self, init_x, init_y, dt=1.0/30.0):
        # 4 state variables: [x, y, vx, vy]
        # 2 measurement variables: [x, y]
        self.kf = KalmanFilter(dim_x=4, dim_z=2)
        
        # Initial state
        self.kf.x = np.array([float(init_x), float(init_y), 0.0, 0.0])
        
        # State transition matrix
        self.kf.F = np.array([
            [1.0, 0.0, dt,  0.0],
            [0.0, 1.0, 0.0, dt ],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0]
        ])
        
        # Measurement matrix (we only measure position x and yī)
        self.kf.H = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0]
        ])
        
        # Measurement noise covariance matrix (R)
        # Assume ~4 pixel measurement standard deviation (variance = 16.0)
        self.kf.R = np.eye(2) * 16.0
        
        # Process noise covariance matrix (Q)
        # Model process variance as small for position, larger for velocity (fast changes)
        q_pos = 1.0
        q_vel = 20.0
        self.kf.Q = np.array([
            [q_pos, 0.0,   0.0,   0.0],
            [0.0,   q_pos, 0.0,   0.0],
            [0.0,   0.0,   q_vel, 0.0],
            [0.0,   0.0,   0.0,   q_vel]
        ])
        
        # State covariance matrix (P)
        # Start with moderately high uncertainty
        self.kf.P = np.eye(4) * 100.0
        
        self.missed_frames = 0
        self.active = True

    def predict(self, dt=None):
        """Predicts the next state. Optionally updates time step dt dynamically."""
        if dt is not None:
            self.kf.F[0, 2] = dt
            self.kf.F[1, 3] = dt
        self.kf.predict()

    def update(self, x, y):
        """Corrects state using the measured coordinates."""
        self.kf.update(np.array([float(x), float(y)]))
        self.missed_frames = 0
        self.active = True

    def get_state(self):
        """Returns the current state vector: (x, y, vx, vy)."""
        return float(self.kf.x[0]), float(self.kf.x[1]), float(self.kf.x[2]), float(self.kf.x[3])


class StickTrackerManager:
    """Manages Left and Right stick tracking, handling L/R association and coasting."""
    def __init__(self, pad_cx, pad_cy, max_missed_frames=10):
        self.pad_cx = pad_cx
        self.pad_cy = pad_cy
        self.max_missed_frames = max_missed_frames
        
        self.left_tracker = None
        self.right_tracker = None
        self.last_time = time.time()

    def update(self, detections):
        """
        Updates trackers with a list of raw detections [(x, y, color), ...] where color is 'R' for red or 'B' for blue.
        Returns a dictionary containing the L and R states.
        """

        now = time.time()
        dt = now - self.last_time
        self.last_time = now

        # Predict next step for active trackers
        if self.left_tracker and self.left_tracker.active:
            self.left_tracker.predict(dt)
        if self.right_tracker and self.right_tracker.active:
            self.right_tracker.predict(dt)

        # Separate detections by color ('R' for red stick -> left, 'B' for blue stick -> right)
        left_detections = []
        right_detections = []
        for det in detections:
            if len(det) != 3:
                continue
            x, y, col = det
            if col == 'R':
                left_detections.append((x, y))
            elif col == 'B':
                right_detections.append((x, y))

        # Update or initialize left tracker
        if left_detections:
            if self.left_tracker and self.left_tracker.active:
                # Choose detection closest to current estimate
                lx, ly = self.left_tracker.get_state()[:2]
                best = min(left_detections, key=lambda p: np.hypot(p[0] - lx, p[1] - ly))
                self.left_tracker.update(*best)
            else:
                det_x, det_y = left_detections[0]
                self.left_tracker = StickKalmanTracker(det_x, det_y, dt=dt)
                print(f"Left stick initialized at ({det_x}, {det_y})")

        # Update or initialize right tracker
        if right_detections:
            if self.right_tracker and self.right_tracker.active:
                rx, ry = self.right_tracker.get_state()[:2]
                best = min(right_detections, key=lambda p: np.hypot(p[0] - rx, p[1] - ry))
                self.right_tracker.update(*best)
            else:
                det_x, det_y = right_detections[0]
                self.right_tracker = StickKalmanTracker(det_x, det_y, dt=dt)
                print(f"Right stick initialized at ({det_x}, {det_y})")

        # Handle trackers that didn't receive a measurement (Coasting)
        if self.left_tracker and self.left_tracker.active and not left_detections:
            self.left_tracker.missed_frames += 1
            if self.left_tracker.missed_frames > self.max_missed_frames:
                self.left_tracker.active = False
                print("Left stick tracking lost.")
        if self.right_tracker and self.right_tracker.active and not right_detections:
            self.right_tracker.missed_frames += 1
            if self.right_tracker.missed_frames > self.max_missed_frames:
                self.right_tracker.active = False
                print("Right stick tracking lost.")

        # 5. Build output states
        output = {}
        if self.left_tracker and self.left_tracker.active:
            output['L'] = self.left_tracker.get_state()
        if self.right_tracker and self.right_tracker.active:
            output['R'] = self.right_tracker.get_state()
            
        return output
