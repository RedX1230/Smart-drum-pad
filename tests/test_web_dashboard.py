import yaml
import pytest

from src import web_dashboard as wd
from src.metrics_collector import MetricsCollector
from src.pattern_evaluator import PatternEvaluator
from src.session_recorder import SessionRecorder

SAMPLE_CONFIG = {
    "camera": {"index": 1, "width": 640, "height": 480},
    "calibration": {"center_x": 361, "center_y": 242, "radius": 206, "rim_width": 9},
    "zones": {"inner": 0.2, "middle": 0.5, "outer": 0.8},
    "audio": {"device_index": None, "latency_ms": 0.0, "sample_rate": 44100, "threshold": 0.05},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(SAMPLE_CONFIG))
    monkeypatch.setattr(wd, "CONFIG_PATH", str(cfg_path))
    wd.set_collector(MetricsCollector())
    wd.set_pattern_evaluator(None)
    wd.recorder = SessionRecorder(path=tmp_path / "sessions.json")
    wd.app.config.update(TESTING=True)
    return wd.app.test_client(), cfg_path


def test_ingest_counts_once(env):
    wd.set_pattern_evaluator(PatternEvaluator("LR"))
    wd.ingest_strike({"stick": "L", "x": 1, "y": 1, "timestamp": 0.0, "zone": "center"})
    assert wd.collector.strike_counts == {"L": 1, "R": 0}
    # pattern evaluator was also fed
    wd.ingest_strike({"stick": "R", "x": 1, "y": 1, "timestamp": 0.5, "zone": "rim"})
    client, _ = env
    assert client.get("/score").get_json()["score"] == 1.0


def test_metrics_endpoint(env):
    client, _ = env
    wd.ingest_strike({"stick": "L", "x": 1, "y": 1, "timestamp": 0.0, "zone": "inner"})
    body = client.get("/metrics").get_json()
    assert body["strike_counts"]["L"] == 1
    assert body["zone_hits"]["inner"] == 1


def test_set_pattern_then_score(env):
    client, _ = env
    assert client.get("/score").get_json()["score"] == 0.0
    client.post("/set_pattern", json={"pattern": "lr"})
    wd.ingest_strike({"stick": "L"})
    wd.ingest_strike({"stick": "R"})
    assert client.get("/score").get_json()["score"] == 1.0


def test_config_get(env):
    client, _ = env
    body = client.get("/config").get_json()
    assert set(body) == {"camera", "calibration", "zones", "audio"}


def test_config_post_whitelists_and_persists(env):
    client, cfg_path = env
    r = client.post("/config", json={"zones": {"inner": 0.3}, "hacker": {"x": 1}, "audio": {"threshold": 0.09}})
    assert r.get_json()["ok"] is True
    on_disk = yaml.safe_load(cfg_path.read_text())
    assert on_disk["zones"]["inner"] == 0.3
    assert on_disk["audio"]["threshold"] == 0.09
    assert "hacker" not in on_disk


def test_config_post_ignores_unknown_field(env):
    client, cfg_path = env
    client.post("/config", json={"zones": {"inner": 0.3, "bogus": 9}})
    on_disk = yaml.safe_load(cfg_path.read_text())
    assert "bogus" not in on_disk["zones"]


def test_session_roundtrip(env):
    client, _ = env
    client.post("/session", json={"pattern": "Single stroke", "bpm": 90, "accuracy": 88, "junk": "x"})
    sessions = client.get("/sessions").get_json()
    assert len(sessions) == 1
    assert sessions[0]["accuracy"] == 88
    assert "junk" not in sessions[0]


def test_post_strike_route_removed(env):
    client, _ = env
    assert client.post("/post_strike", json={"stick": "L"}).status_code == 404


def test_config_post_non_dict_group_is_ignored(env):
    client, cfg_path = env
    r = client.post("/config", json={"zones": "not-a-dict"})
    assert r.get_json()["ok"] is True
    on_disk = yaml.safe_load(cfg_path.read_text())
    assert on_disk["zones"]["inner"] == 0.2  # unchanged


def test_config_post_empty_body(env):
    client, _ = env
    assert client.post("/config", json={}).get_json()["ok"] is True


def test_sessions_delete(env):
    client, _ = env
    client.post("/session", json={"pattern": "a"})
    assert len(client.get("/sessions").get_json()) == 1
    assert client.delete("/sessions").get_json()["ok"] is True
    assert client.get("/sessions").get_json() == []


def test_sessions_csv(env):
    client, _ = env
    client.post("/session", json={"pattern": "Paradiddle", "bpm": 100, "accuracy": 91})
    r = client.get("/sessions.csv")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    text = r.get_data(as_text=True)
    assert "pattern" in text.splitlines()[0]
    assert "Paradiddle" in text

