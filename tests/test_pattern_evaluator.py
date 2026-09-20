from src.pattern_evaluator import PatternEvaluator


def feed(ev, seq):
    for s in seq:
        ev.add_strike({"stick": s})
    return ev


def test_empty_pattern_scores_zero():
    assert PatternEvaluator("").evaluate() == 0.0


def test_too_few_strikes_scores_zero():
    ev = feed(PatternEvaluator("LRLR"), "LR")
    assert ev.evaluate() == 0.0


def test_exact_match():
    ev = feed(PatternEvaluator("LR"), "LR")
    assert ev.evaluate() == 1.0


def test_partial_match():
    ev = feed(PatternEvaluator("LRLR"), "LRRR")
    assert ev.evaluate() == 0.75


def test_uses_only_most_recent_window():
    # Older wrong strikes should not count once enough have been played.
    ev = feed(PatternEvaluator("LR"), "RRLR")
    assert ev.evaluate() == 1.0


def test_case_insensitive_and_ignores_other_chars():
    ev = PatternEvaluator("l-r x")
    assert ev.pattern == ["L", "R"]
    feed(ev, "lr")
    assert ev.evaluate() == 1.0


def test_history_is_trimmed():
    ev = feed(PatternEvaluator("LR"), "L" * 50)
    assert len(ev.history) <= max(10, len(ev.pattern) * 2)
