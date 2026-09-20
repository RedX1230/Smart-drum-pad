from src.metrics_collector import MetricsCollector


def strike(stick, zone=None, ts=0.0):
    s = {"stick": stick, "x": 100, "y": 100, "timestamp": ts}
    if zone is not None:
        s["zone"] = zone
    return s


def test_strike_counts():
    c = MetricsCollector()
    c.add_strike(strike("L"))
    c.add_strike(strike("R"))
    c.add_strike(strike("L"))
    assert c.strike_counts == {"L": 2, "R": 1}


def test_zone_hits_match_get_zone_name_vocab():
    c = MetricsCollector()
    for z in ("center", "inner", "outer", "rim"):
        c.add_strike(strike("L", zone=z))
    assert c.zone_hits == {"center": 1, "inner": 1, "outer": 1, "rim": 1}


def test_unknown_zone_ignored():
    c = MetricsCollector()
    c.add_strike(strike("L", zone="middle"))  # not a real region label
    assert sum(c.zone_hits.values()) == 0


def test_bpm_from_even_spacing():
    c = MetricsCollector()
    for i in range(4):
        c.add_strike(strike("L", ts=i * 0.5))  # 0.5s apart -> 120 bpm
    assert abs(c._compute_bpm() - 120.0) < 1e-6


def test_bpm_needs_two_strikes():
    c = MetricsCollector()
    c.add_strike(strike("L", ts=1.0))
    assert c._compute_bpm() == 0.0


def test_push_frame_speed_and_to_dict():
    c = MetricsCollector()
    c.push_frame(0.0, (0.0, 0.0), None)
    c.push_frame(1.0, (3.0, 4.0), None)  # moved 5px in 1s
    d = c.to_dict()
    assert abs(d["left_speed"] - 5.0) < 1e-6
    assert d["right_speed"] == 0.0
    assert "bpm" in d and "zone_hits" in d


def test_recent_strikes_capped_in_output():
    c = MetricsCollector()
    for i in range(15):
        c.add_strike(strike("L", ts=float(i)))
    assert len(c.to_dict()["recent_strikes"]) == 10


def test_bpm_zero_interval_is_safe():
    c = MetricsCollector()
    c.add_strike(strike("L", ts=1.0))
    c.add_strike(strike("L", ts=1.0))  # duplicate timestamp -> no division blow-up
    assert c._compute_bpm() == 0.0


def test_strike_history_does_not_grow_unbounded():
    c = MetricsCollector()
    for i in range(5000):
        c.add_strike(strike("L", ts=float(i)))
    # A long session must not accumulate every strike forever.
    assert len(c.strikes) <= 1000
