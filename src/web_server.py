"""Simple Flask server to serve the web UI and sync with the Python backend.

Endpoints:
- ``/``               – serves ``web/index.html`` (static files are auto‑served by Flask).
- ``/chart``          – returns the selected chart JSON (default demo).
- ``/post_strike``   – POST endpoint called by the backend (``src/main.py``) to forward a strike.
- ``/get_strikes``   – GET endpoint polled by the web UI to retrieve recent strikes.

The server stores the most recent strikes in a thread‑safe list (max 10) so the
frontend can display them in near‑real‑time.  This keeps the architecture simple
without requiring websockets.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path
from typing import List, Dict, Any

from flask import Flask, send_from_directory, jsonify, request, abort

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_ROOT = Path(__file__).parent.parent  # project root
WEB_ROOT = APP_ROOT / "web"
CHART_PATH = APP_ROOT / "charts" / "demo.json"
MAX_STORED_STRIKES = 10

app = Flask(__name__, static_folder=str(WEB_ROOT), static_url_path="")

# ---------------------------------------------------------------------------
# In‑memory strike buffer (thread‑safe)
# ---------------------------------------------------------------------------
_strike_lock = threading.Lock()
_strike_buffer: deque[Dict[str, Any]] = deque(maxlen=MAX_STORED_STRIKES)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def serve_index():
    return send_from_directory(str(WEB_ROOT), "index.html")

@app.route("/chart")
def serve_chart():
    if not CHART_PATH.exists():
        abort(404, description="Chart not found")
    with open(CHART_PATH, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    return jsonify(data)

@app.route("/post_strike", methods=["POST"])
def receive_strike():
    if not request.is_json:
        abort(400, description="Expected JSON payload")
    strike = request.get_json()
    # Minimal validation – ensure required keys exist
    required = {"timestamp", "stick", "x", "y", "label"}
    if not required.issubset(strike):
        abort(400, description="Missing required fields")
    with _strike_lock:
        _strike_buffer.appendleft(strike)  # newest first
    return "OK", 200

@app.route("/get_strikes")
def get_strikes():
    with _strike_lock:
        # Return a copy to avoid race conditions
        strikes = list(_strike_buffer)
    return jsonify(strikes)

# ---------------------------------------------------------------------------
# Helper for development
# ---------------------------------------------------------------------------
def run_server(host: str = "127.0.0.1", port: int = 5000):
    """Start the Flask development server.

    In production you would run behind a proper WSGI server, but for the demo
    this is sufficient.
    """
    app.run(host=host, port=port, debug=False, use_reloader=False)

# ---------------------------------------------------------------------------
# Allow ``python -m src.web_server`` to launch the server directly.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_server()
