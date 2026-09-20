import pytest

pytest.importorskip("cv2")
pytest.importorskip("numpy")

from src.zone_highlighter import ZoneHighlighter

RATIOS = {"inner": 0.2, "middle": 0.5, "outer": 0.8}


def make():
    # centre (100,100), radius 100, rim 10, explicit ratios (no config read)
    return ZoneHighlighter(100, 100, 100, 10, zone_ratios=RATIOS)


def test_center():
    assert make().get_zone_name(100, 100) == "center"


def test_inner_band():
    # distance 30 -> between inner_r(20) and middle_r(50)
    assert make().get_zone_name(130, 100) == "inner"


def test_outer_band():
    # distance 70 -> between middle_r(50) and outer_r(80)
    assert make().get_zone_name(170, 100) == "outer"


def test_rim():
    # distance 105 -> beyond R(100) but within R+rim(110)
    assert make().get_zone_name(205, 100) == "rim"


def test_off_pad_is_none():
    assert make().get_zone_name(300, 300) is None
