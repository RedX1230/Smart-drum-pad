"""Rule‑based accent / rim‑shot detection.

The rest of the code base already knows the strike position (x, y) and
the audio peak level in decibels (`peak_db`).  A rim‑shot is a positional
event – the stick hit the rim of the pad – while the dynamic level
(ghost / normal / accent) is purely an audio property.  We therefore
use a tiny deterministic function instead of a learned model.

The public entry point is :func:`classify_strike`.  It receives the audio
peak (in dB) and the zone name (as returned by ``ZoneHighlighter``) and
returns one of the five labels used throughout the project:

* ``rimshot`` – hit on the rim regardless of amplitude
* ``accent``  – loud hit (default > -6 dB)
* ``normal``  – medium hit (default between -18 dB and -6 dB)
* ``ghost``   – soft hit (default ≤ -18 dB)
* ``unlabeled`` – fallback for unexpected inputs

Thresholds can be tuned by editing ``ACCENT_THRESH`` / ``NORMAL_THRESH``.
"""

from __future__ import annotations

# Default decibel thresholds – these work well for the recorded data but
# can be changed without touching any other code.
ACCENT_THRESH = -6.0   # dB above which we call the hit an "accent"
NORMAL_THRESH = -18.0  # dB above which we call the hit a "normal"


def _classify_dynamic(peak_db: float) -> str:
    """Return ``accent``, ``normal`` or ``ghost`` based on *peak_db*.

    The function is intentionally simple: a single comparison against two
    thresholds.  ``peak_db`` is expected to be a negative value because it
    is a relative level to 0 dBFS.  The thresholds are configurable at the
    module level.
    """
    if peak_db > ACCENT_THRESH:
        return "accent"
    if peak_db > NORMAL_THRESH:
        return "normal"
    return "ghost"


def classify_strike(peak_db: float, zone_name: str | None) -> str:
    """Classify a strike into ``rimshot`` or a dynamic label.

    Parameters
    ----------
    peak_db:
        Peak amplitude of the audio transient in dBFS.  The value is taken
        directly from ``AudioStrikeDetector.last_peak_db``.
    zone_name:
        Name of the pad zone as returned by ``ZoneHighlighter.get_zone_name``.
        Expected values are ``"center"``, ``"inner"``, ``"outer"`` or
        ``"rim"``.  ``None`` or any unknown value is treated as a normal
        non‑rim hit.

    Returns
    -------
    str
        One of ``"rimshot"``, ``"accent"``, ``"normal"``, ``"ghost"`` or
        ``"unlabeled"``.
    """
    # Rim‑shot is purely positional – we ignore the audio level.
    if zone_name == "rim":
        return "rimshot"
    if zone_name is None:
        # Defensive fallback – treat as unknown location.
        return "unlabeled"
    # Otherwise classify by audio intensity.
    return _classify_dynamic(peak_db)


def augment_strike(strike: dict, zone_name: str | None) -> dict:
    """Add an ``"accent"`` (or ``"rimshot"``) label to a strike dict.

    The function mutates the supplied ``strike`` mapping in‑place and also
    returns it for convenience.
    """
    peak_db = strike.get("peak_db", -60.0)  # very low default – will be ghost
    strike["label"] = classify_strike(peak_db, zone_name)
    return strike

__all__ = ["classify_strike", "augment_strike"]
