from flask import Flask, jsonify, request, send_from_directory
from threading import Thread
import os
import logging

# Silence Flask/Werkzeug logs so they don't hide the interactive terminal prompts
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Absolute path to the static folder in the project root
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))

# Flask app – serve UI from the 'static' folder (HTML, CSS, JS)
app = Flask(__name__, static_folder=static_dir, static_url_path='/static')
collector = None
pattern_evaluator = None

def set_collector(col):
    """Register the MetricsCollector instance for the Flask routes."""
    global collector
    collector = col

def set_pattern_evaluator(evaluator):
    """Register the PatternEvaluator instance for the Flask routes."""
    global pattern_evaluator
    pattern_evaluator = evaluator

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

@app.route('/post_strike', methods=['POST'])
def post_strike():
    """Receive a strike from the core app, forward it to the collector and optionally the pattern evaluator."""
    data = request.get_json()
    if collector is not None and data:
        collector.add_strike(data)
    if pattern_evaluator is not None and data:
        pattern_evaluator.add_strike(data)
    return ('', 204)

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
