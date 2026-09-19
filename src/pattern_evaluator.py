class PatternEvaluator:
    """Evaluates a user‑provided stick pattern against detected strikes.

    The pattern is a string like "lrlrlr" (case‑insensitive). The evaluator
    stores a rolling list of recent strike stick labels and compares the most
    recent <len(pattern)> strikes to the target pattern.
    """

    def __init__(self, pattern: str):
        # Normalise to a list of uppercase "L"/"R" characters
        self.pattern = [c.upper() for c in pattern if c.upper() in ("L", "R")]
        self.history: list[str] = []  # recent stick labels

    def add_strike(self, strike: dict) -> None:
        stick = strike.get("stick")
        if stick:
            self.history.append(stick.upper())
            # Trim history to a reasonable size (twice pattern length)
            max_len = max(10, len(self.pattern) * 2)
            if len(self.history) > max_len:
                self.history = self.history[-max_len:]

    def evaluate(self) -> float:
        """Return a score 0‑1 indicating how well the recent strikes match
        the expected pattern. If there are fewer than ``len(pattern)`` strikes
        the score is 0.
        """
        if not self.pattern:
            return 0.0
        if len(self.history) < len(self.pattern):
            return 0.0
        recent = self.history[-len(self.pattern) :]
        matches = sum(1 for a, b in zip(recent, self.pattern) if a == b)
        return matches / len(self.pattern)
