from flask import Flask, jsonify, request, send_from_directory
from threading import Thread
import os
import logging
import yaml

from src.session_recorder import SessionRecorder

# Silence Flask/Werkzeug logs so they don't hide the interactive terminal prompts
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
static_dir = os.path.join(BASE_DIR, 'static')
CONFIG_PATH = os.path.join(BASE_DIR, 'config.yaml')

# Flask app – serve UI from the 'static' folder (HTML, CSS, JS)
app = Flask(__name__, static_folder=static_dir, static_url_path='/static')
collector = None
pattern_evaluator = None
recorder = SessionRecorder()

# Editable config keys, grouped, with a coercion function. Anything outside
# this whitelist is ignored on write so the web UI can't corrupt config.yaml.
_EDITABLE = {
    'camera':      {'index': int, 'width': int, 'height': int},
    'calibration': {'center_x': int, 'center_y': int, 'radius': int, 'rim_width': int},
    'zones':       {'inner': float, 'middle': float, 'outer': float},
    'audio':       {'threshold': float, 'sample_rate': int, 'device_index': int, 'latency_ms': float},
}


def set_collector(col):
    """Register the MetricsCollector instance for the Flask routes."""
    global collector
    collector = col


def set_pattern_evaluator(evaluator):
    """Register the PatternEvaluator instance for the Flask routes."""
    global pattern_evaluator
    pattern_evaluator = evaluator


def ingest_strike(strike):
    """Single ingestion point for a detected strike: feeds the metrics
    collector and the pattern evaluator. Called directly by the core loop
    (in-process) so there is no HTTP round-trip and no double counting."""
    if collector is not None and strike:
        collector.add_strike(strike)
    if pattern_evaluator is not None and strike:
        pattern_evaluator.add_strike(strike)


def _load_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f) or {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


# ---------------------------------------------------------------------
# UI route
# ---------------------------------------------------------------------
@app.route('/')
def index():
    """Serve the main dashboard page (index.html)."""
    return send_from_directory(app.static_folder, 'index.html')


# ---------------------------------------------------------------------
# Data API routes
# ---------------------------------------------------------------------
@app.route('/metrics')
def metrics():
    """Return the latest collected metrics as JSON."""
    if collector is None:
        return jsonify({})
    return jsonify(collector.to_dict())


@app.route('/set_pattern', methods=['POST'])
def set_pattern():
    """Create or replace the PatternEvaluator with a user‑supplied pattern.
    Expected JSON payload: {"pattern": "lrlrlr"}
    """
    payload = request.get_json(silent=True) or {}
    pat = payload.get('pattern', '')
    if pat:
        from src.pattern_evaluator import PatternEvaluator
        global pattern_evaluator
        pattern_evaluator = PatternEvaluator(pat)
    return ('', 204)


@app.route('/score')
def score():
    """Return the current pattern match score (0‑1)."""
    if pattern_evaluator is None:
        return jsonify({"score": 0.0})
    return jsonify({"score": pattern_evaluator.evaluate()})


@app.route('/config', methods=['GET', 'POST'])
def config():
    """GET: camera / calibration / zone / audio settings for the UI.
    POST: merge whitelisted numeric settings back into config.yaml so the
    Setup screen can tune the pad. Applied on the next detector start."""
    if request.method == 'GET':
        return jsonify(_load_config())

    payload = request.get_json(silent=True) or {}
    cfg = _load_config()
    for group, fields in _EDITABLE.items():
        incoming = payload.get(group)
        if not isinstance(incoming, dict):
            continue
        section = cfg.setdefault(group, {})
        for key, cast in fields.items():
            if key in incoming and incoming[key] is not None:
                try:
                    section[key] = cast(incoming[key])
                except (TypeError, ValueError):
                    continue
    try:
        with open(CONFIG_PATH, 'w') as f:
            yaml.safe_dump(cfg, f, default_flow_style=False)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "config": cfg})


@app.route('/session', methods=['POST'])
def save_session():
    """Persist a finished practice session (summary computed by the UI)."""
    data = request.get_json(silent=True) or {}
    recorder.add(data)
    return jsonify({"ok": True})


@app.route('/sessions', methods=['GET', 'DELETE'])
def list_sessions():
    """GET: stored practice sessions, newest first. DELETE: clear them all."""
    if request.method == 'DELETE':
        recorder.clear()
        return jsonify({"ok": True})
    return jsonify(recorder.all())


_CSV_FIELDS = [
    'recorded_at', 'pattern', 'bpm', 'duration_s', 'strikes', 'accuracy',
    'mean_ms', 'spread_ms', 'best_streak', 'left', 'right', 'wrong_hand',
    'missed', 'extra', 'perfect', 'good', 'okay',
]


@app.route('/sessions.csv')
def sessions_csv():
    """Download the session log as CSV, oldest first."""
    import csv
    import io
    from datetime import datetime, timezone

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction='ignore')
    writer.writeheader()
    for s in reversed(recorder.all()):  # chronological
        row = dict(s)
        if 'recorded_at' in row:
            row['recorded_at'] = datetime.fromtimestamp(row['recorded_at'], timezone.utc).isoformat()
        writer.writerow(row)
    return app.response_class(
        buf.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=smart-drum-pad-sessions.csv'},
    )


# ---------------------------------------------------------------------
# Server launch helper
# ---------------------------------------------------------------------
def _run():
    # Run without Flask reloader or debugger – launched in a daemon thread
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)


def start_web_server(col):
    """Start Flask server in a background daemon thread and bind the collector.

    ``col`` – the MetricsCollector instance created by the main program.
    """
    set_collector(col)
    t = Thread(target=_run, daemon=True)
    t.start()
