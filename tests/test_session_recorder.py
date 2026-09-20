import json

from src.session_recorder import SessionRecorder


def test_add_whitelists_and_timestamps(tmp_path):
    rec = SessionRecorder(path=tmp_path / "s.json")
    saved = rec.add({"pattern": "Single stroke", "bpm": 90, "accuracy": 100, "evil": "drop me"})
    assert "evil" not in saved
    assert saved["pattern"] == "Single stroke"
    assert saved["bpm"] == 90.0
    assert "recorded_at" in saved


def test_newest_first(tmp_path):
    rec = SessionRecorder(path=tmp_path / "s.json")
    rec.add({"pattern": "first"})
    rec.add({"pattern": "second"})
    order = [s["pattern"] for s in rec.all()]
    assert order == ["second", "first"]


def test_cap(tmp_path):
    rec = SessionRecorder(path=tmp_path / "s.json", max_sessions=3)
    for i in range(6):
        rec.add({"pattern": str(i)})
    got = [s["pattern"] for s in rec.all()]
    assert got == ["5", "4", "3"]


def test_coercion_and_bad_values(tmp_path):
    rec = SessionRecorder(path=tmp_path / "s.json")
    saved = rec.add({"bpm": "120", "accuracy": "not-a-number", "strikes": 8})
    assert saved["bpm"] == 120.0
    assert "accuracy" not in saved
    assert saved["strikes"] == 8


def test_persists_across_instances(tmp_path):
    p = tmp_path / "s.json"
    SessionRecorder(path=p).add({"pattern": "kept"})
    assert [s["pattern"] for s in SessionRecorder(path=p).all()] == ["kept"]


def test_corrupt_file_is_ignored(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{ not valid json")
    rec = SessionRecorder(path=p)
    assert rec.all() == []
    rec.add({"pattern": "ok"})  # recovers by overwriting
    assert [s["pattern"] for s in rec.all()] == ["ok"]


def test_long_string_truncated(tmp_path):
    rec = SessionRecorder(path=tmp_path / "s.json")
    saved = rec.add({"pattern": "x" * 500})
    assert len(saved["pattern"]) <= 60
