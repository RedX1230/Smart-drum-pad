from src.accent_detection import classify_strike, augment_strike


def test_rim_is_always_rimshot():
    assert classify_strike(0.0, "rim") == "rimshot"
    assert classify_strike(-40.0, "rim") == "rimshot"


def test_dynamic_levels_by_threshold():
    assert classify_strike(-3.0, "center") == "accent"
    assert classify_strike(-12.0, "inner") == "normal"
    assert classify_strike(-30.0, "outer") == "ghost"


def test_boundaries():
    # ACCENT_THRESH = -6, NORMAL_THRESH = -18 (strict >)
    assert classify_strike(-6.0, "center") == "normal"
    assert classify_strike(-18.0, "center") == "ghost"


def test_none_zone_is_unlabeled():
    assert classify_strike(-3.0, None) == "unlabeled"


def test_augment_mutates_and_returns():
    strike = {"peak_db": -3.0}
    out = augment_strike(strike, "center")
    assert out is strike
    assert strike["label"] == "accent"


def test_augment_default_peak_is_ghost():
    strike = {}
    augment_strike(strike, "center")
    assert strike["label"] == "ghost"
