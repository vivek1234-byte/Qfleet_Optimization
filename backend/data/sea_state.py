"""
Sea-state alerts: which lanes are rough this month, and how rough.

Built from the two things this platform genuinely knows about weather — each
lane's annual-mean Beaufort in the registry, and the monthly basin
climatology in ``seasonality`` — and from the Beaufort scale itself, which is
a published WMO table rather than anything invented here.

**What this does not do: tides.** There is no tide model, no harmonic
constituents and no station feed anywhere in this project, so there is no
honest way to raise a high-tide alert. A tide warning fabricated from nothing
would be indistinguishable from a real one on screen and worse than no
warning at all, so the alert set stops at sea state. ``TIDES_UNAVAILABLE``
below is what the API reports instead, and wiring a real source is a small
job once there is one — see the note on that constant.

The wave heights are the WMO sea-state bands that correspond to each Beaufort
force. They are what the scale means, not a second guess layered on top: a
lane at force 7 has a 4-metre significant wave height by definition of force
7. What remains indicative is the *Beaufort* figure itself, because it comes
from the climatology, and every payload says so.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .seasonality import MONTH_NAMES, seasonal_factor
from .weather_feed import ATTRIBUTION, fetch_marine, feed_status

#: WMO Beaufort scale: force → (description, significant wave height in metres).
#: The wave height is the mid-band figure for that force.
BEAUFORT_SCALE: Dict[int, tuple[str, float]] = {
    0: ("Calm", 0.0),
    1: ("Light air", 0.1),
    2: ("Light breeze", 0.2),
    3: ("Gentle breeze", 0.6),
    4: ("Moderate breeze", 1.0),
    5: ("Fresh breeze", 2.0),
    6: ("Strong breeze", 3.0),
    7: ("Near gale", 4.0),
    8: ("Gale", 5.5),
    9: ("Strong gale", 7.0),
    10: ("Storm", 9.0),
    11: ("Violent storm", 11.5),
    12: ("Hurricane force", 14.0),
}

#: Thresholds.
#:
#: Calibrated against what this registry actually contains, which matters:
#: across all sixteen lanes and all twelve months the climatology never
#: exceeds force 5.9, so a scale hung on "gale force or nothing" would have
#: stayed silent all year and the feature would have been decoration.
#:
#: The signal that IS present — and the one a fleet planner actually misses —
#: is a lane running well above its own annual mean. A lane that sits at
#: force 5 every month is not news in July; one that normally sits at 3.8 and
#: reaches 5.5 is, because the schedule and the fuel burn were planned
#: against the mean. So severity is driven by deterioration, with absolute
#: force as an escalator that fires the day someone swaps the climatology for
#: a real met feed.
#:
#: Severity is named for operational impact rather than for the weather,
#: deliberately. Calling a force-5.5 lane "severe weather" would be a lie;
#: calling it high-impact when it is 45% rougher than the voyage was planned
#: for is not. Every alert carries the absolute force and wave height as
#: well, so the number behind the label is always on screen.
HIGH_DEVIATION = 0.30      # +30% over the lane's annual mean
MODERATE_DEVIATION = 0.18
WATCH_DEVIATION = 0.10

#: Absolute Beaufort escalators. Inert on the bundled climatology, live the
#: moment a real feed replaces it — which is the point of keeping them.
ROUGH_FORCE = 6.0          # strong breeze, 3 m seas
SEVERE_FORCE = 7.0         # near gale, 4 m seas

SEVERITY_LABEL = {
    "high": "High impact",
    "moderate": "Moderate impact",
    "watch": "Watch",
}

#: Reported by the API in place of a tide alert. Kept as a constant rather
#: than a string in the endpoint so it is one edit when a feed arrives:
#: implement `tide_alerts(ports, when)` here, returning the same Alert shape,
#: and add it to `build_alerts`.
TIDES_UNAVAILABLE = (
    "Tides and storm surge are not modelled. This platform has no tide "
    "harmonics or station feed, so no high-tide warning is raised — an "
    "invented one would look identical to a real one."
)


def describe_force(force: float) -> tuple[str, float]:
    """Label and significant wave height for a (possibly fractional) force."""
    step = max(0, min(12, int(round(force))))
    return BEAUFORT_SCALE[step]


def _severity(force: float, ratio: float) -> Optional[str]:
    """
    How much this lane should worry a planner, or None if it should not.

    Whichever is worse: how rough the water is in absolute terms, or how far
    above this lane's own normal it has moved.
    """
    deviation = ratio - 1.0
    if force >= SEVERE_FORCE or deviation >= HIGH_DEVIATION:
        return "high"
    if force >= ROUGH_FORCE or deviation >= MODERATE_DEVIATION:
        return "moderate"
    if deviation >= WATCH_DEVIATION:
        return "watch"
    return None


def lane_sea_state(lane, month: int) -> Dict[str, Any]:
    """
    What the sea is doing on one lane in one month.

    Always returned, alert or not, so a caller can show the calm lanes too.
    """
    factor = seasonal_factor(lane.basins, month)
    baseline = float(lane.weather_beaufort)
    force = baseline * factor
    label, wave_m = describe_force(force)
    return {
        "lane": lane.name,
        "origin": lane.origin,
        "destination": lane.destination,
        "month": month,
        "month_name": MONTH_NAMES[month - 1],
        "annual_mean_beaufort": round(baseline, 2),
        "beaufort": round(force, 1),
        "seasonal_factor": round(factor, 3),
        # How much rougher than this lane's own normal year.
        "vs_annual_pct": round((factor - 1.0) * 100, 1),
        "description": label,
        "significant_wave_m": wave_m,
        "basins": [{"basin": b, "share": w} for b, w in lane.basins],
    }


def _live_lane_state(lane, month: int, live: Dict[str, Any]) -> Dict[str, Any]:
    """
    One lane's state from the feed rather than from the climatology.

    The observed Beaufort replaces the estimate, and the wave height is the
    model's own rather than the WMO band for that force — the whole point of
    a live feed is that it measures the sea instead of inferring it.
    ``vs_annual_pct`` still compares against this lane's registry mean, which
    is what makes an alert actionable: it says how far today departs from
    what the voyage was planned against.
    """
    state = lane_sea_state(lane, month)
    baseline = state["annual_mean_beaufort"]
    force = float(live["beaufort"])
    label, _band = describe_force(force)
    state.update(
        {
            "beaufort": round(force, 1),
            "description": label,
            "significant_wave_m": live["wave_height_m"],
            "swell_height_m": live.get("swell_height_m"),
            "wave_period_s": live.get("wave_period_s"),
            "wind_knots": live.get("wind_knots"),
            "wind_gust_knots": live.get("wind_gust_knots"),
            "beaufort_basis": live.get("beaufort_basis"),
            "vs_annual_pct": round(((force / baseline) - 1.0) * 100, 1) if baseline else 0.0,
            "seasonal_factor": round(force / baseline, 3) if baseline else 1.0,
            "source": "observed",
        }
    )
    return state


def _lane_sample_point(lane) -> Optional[tuple]:
    """Where on the lane to ask about the weather — its midpoint at sea."""
    try:
        from .sea_routes import lane_points
    except ImportError:  # pragma: no cover - flat import layout
        from sea_routes import lane_points  # type: ignore
    points = lane_points(lane)
    if not points:
        return None
    return points[len(points) // 2]


def build_alerts(lanes, month: Optional[int] = None, live: bool = True) -> Dict[str, Any]:
    """
    Every lane whose sea state is worth a warning this month.

    Three levels, worst first — see the threshold constants for why they are
    driven by deterioration rather than by absolute Beaufort on this data:

    * ``high`` — 30% or more above the lane's annual mean, or a genuine gale.
    * ``moderate`` — 18% above, or force 6 and up.
    * ``watch`` — 10% above. Worth knowing before committing to a speed.
    """
    if month is None:
        month = datetime.now(timezone.utc).month
    month = max(1, min(12, int(month)))

    lanes = list(lanes)
    states = [{**lane_sea_state(lane, month), "source": "climatology"} for lane in lanes]

    # Overlay the live feed where it answered. Per lane, not all-or-nothing:
    # a feed that covers fourteen of sixteen lanes should upgrade those
    # fourteen rather than be discarded, and each row says which it is.
    observed_count = 0
    feed_used = False
    if live:
        points = [_lane_sample_point(lane) for lane in lanes]
        askable = [(i, pt) for i, pt in enumerate(points) if pt]
        samples = fetch_marine([pt for _i, pt in askable]) if askable else []
        if samples:
            feed_used = True
            for (index, _pt), sample in zip(askable, samples):
                if sample:
                    states[index] = _live_lane_state(lanes[index], month, sample)
                    observed_count += 1

    alerts: List[Dict[str, Any]] = []
    for state in states:
        severity = _severity(state["beaufort"], state["seasonal_factor"])
        if severity is None:
            continue
        # Both halves, always: the absolute conditions and the departure from
        # normal. Either one alone invites the wrong conclusion — the force
        # reads as mild, the percentage reads as apocalyptic.
        alerts.append({
            **state,
            "severity": severity,
            "severity_label": SEVERITY_LABEL[severity],
            "headline": (
                f"{state['vs_annual_pct']:+.0f}% rougher than this lane's annual mean"
                if state["vs_annual_pct"] > 0
                else state["description"]
            ),
            "detail": (
                f"{state['description']}, force {state['beaufort']:.1f} · "
                f"{state['significant_wave_m']:.1f} m seas"
            ),
        })

    order = {"high": 0, "moderate": 1, "watch": 2}
    alerts.sort(key=lambda a: (order[a["severity"]], -a["beaufort"]))

    counts = {
        level: sum(1 for a in alerts if a["severity"] == level)
        for level in ("high", "moderate", "watch")
    }
    return {
        "month": month,
        "month_name": MONTH_NAMES[month - 1],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {**counts, "total": len(alerts)},
        # The dot goes red at "high" and amber below it.
        "worst_severity": alerts[0]["severity"] if alerts else None,
        "alerts": alerts,
        "lanes_assessed": len(states),
        "lanes_observed": observed_count,
        "live": {
            **feed_status(),
            "requested": live,
            "used": feed_used,
            # The banner the UI shows. Never "live" unless every flagged lane
            # actually came from the feed.
            "mode": (
                "observed"
                if observed_count == len(states) and observed_count > 0
                else "mixed"
                if observed_count
                else "climatology"
            ),
        },
        "thresholds": {
            "high_deviation_pct": HIGH_DEVIATION * 100,
            "moderate_deviation_pct": MODERATE_DEVIATION * 100,
            "watch_deviation_pct": WATCH_DEVIATION * 100,
            "rough_force": ROUGH_FORCE,
            "severe_force": SEVERE_FORCE,
        },
        "basis": (
            f"{observed_count} of {len(states)} lanes from live marine forecast "
            f"({ATTRIBUTION}); the rest from each lane's registry Beaufort scaled "
            "by indicative monthly basin climatology. Every alert carries its own "
            "`source`, so an estimated figure is never presented as a measured one."
            if observed_count
            else "No live feed reached. Every figure is the registry's annual-mean "
            "Beaufort scaled by indicative monthly basin climatology — estimated, "
            "not measured."
        ),
        "not_modelled": {"tides": TIDES_UNAVAILABLE},
    }
