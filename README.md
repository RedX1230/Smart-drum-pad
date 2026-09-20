# Smart Drum Pad

A rhythm-training tool built around **one** physical practice pad. An overhead
camera tracks the left and right stick tips, a microphone times each strike, and
the app judges what you played against a target sticking pattern — where the
stick landed, which hand you used, and whether you sat ahead of or behind the
beat.

The interface is designed like a warm drumming practice book: a **Practice**
screen with a scrolling note lane and a tactile drum, a **Review** of the last
session, a **History** of your progress over time, and a **Setup** page for
calibration.

## How it works

Two pieces run together:

- **Detector (desktop)** — OpenCV camera tracking (`src/`) plus audio
  transient detection. It finds the pad, tracks the two stick tips with a
  Kalman filter, and emits a strike (hand, x/y, hit type) on each audio peak.
- **Web UI (`static/`)** — a Flask server (`src/web_dashboard.py`) serves the
  interface and exposes the detector's live data. Timing is paced in the
  browser against the chosen tempo; every judged strike comes from the real
  detector (or the keyboard, see below).

## Install

```bash
pip install -r requirements.txt
```

## Run

Full rig (camera + microphone), with the detector and desktop tracking window:

```bash
python -m src.main
```

Then open http://127.0.0.1:5000 for the web UI.

Run the web UI on its own (no camera or desktop window) to build patterns,
review past sessions and calibrate:

```bash
python -m src.main --web-only
```

## The screens

- **Practice** — build a sticking pattern with the L/R buttons and presets,
  or type **drum notation** to set both the hand and the target zone per
  note. A note is a hand (`L`/`R`) plus an optional zone letter — `c` centre,
  `i` inner, `o` outer, `r` rim (default centre); for example `L R Li Ro Rr`.
  Set the tempo, optionally turn on the metronome, and play: a 3-count leads
  in, notes descend onto the drum, the target zone glows on the pad, and
  accuracy, streak, score and struck tempo update live.
- **Review** — the last session: key results, a timing plot (ahead/behind the
  beat), target-vs-played pattern, a drum map of where you struck, hit-type
  distribution and detailed metrics.
- **History** — accuracy trend and a log of every saved session; export to CSV
  or clear.
- **Setup** — a live camera/detection preview and editable calibration (pad
  boundary, zones, audio), saved back to `config.yaml`.

## Calibration

Settings live in `config.yaml`. Edit them from the Setup screen (applied on the
next detector start), or run the automatic pad-boundary detector:

```bash
python -m src.calibrate_pad
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
