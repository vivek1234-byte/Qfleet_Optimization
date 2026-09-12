"""
Live marine weather, with the climatology underneath it.

Fetches observed and forecast sea state from Open-Meteo — a free, keyless,
CC-BY service that aggregates national meteorological models (ECMWF, DWD ICON,
Météo-France, NOAA GFS, and others depending on the region). Two endpoints:
the Marine API for wave height, swell and wave period, and the Forecast API
for wind, which is what a Beaufort force actually measures.

Three things this module takes seriously.

**It must never be load-bearing.** The team brief lists venue Wi-Fi as a top
risk, which is why the map ships its own coastline rather than calling a tile
server. The same reasoning applies here: every failure path — no network, a
timeout, a rate limit, a malformed body — falls back to the bundled
climatology and says so. A demo on a dead connection shows estimated figures
labelled as estimated, not an error page.

**Provenance travels with the number.** Every sample carries ``source``:
``observed`` when it came from the feed, ``climatology`` when it did not.
Mixing the two silently would destroy the only thing live data is worth —
that you can trust it. Nothing downstream is allowed to forget which it has.

**One call for the whole fleet.** Open-Meteo accepts comma-separated
coordinate lists, so sixteen lanes cost two HTTP requests rather than
thirty-two. Results are cached for ``CACHE_TTL_SECONDS`` because a marine
forecast updates a few times a day, not a few times a minute.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

#: A marine model run lands every few hours; polling harder gains nothing and
#: risks the fair-use limit.
CACHE_TTL_SECONDS = 30 * 60
#: Short on purpose. A weather panel that makes the whole page wait is worse
#: than one that quietly shows the climatology.
REQUEST_TIMEOUT_SECONDS = 8.0
#: After this many consecutive failures, stop trying until the cooldown ends.
#: Without it an offline venue pays the timeout on every single request.
FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 10 * 60

ATTRIBUTION = "Open-Meteo.com (CC BY 4.0), aggregating national weather services"

#: Beaufort force by upper wind-speed bound in knots. The standard scale.
_BEAUFORT_BOUNDS: Tuple[Tuple[float, int], ...] = (
    (1, 0), (3, 1), (6, 2), (10, 3), (16, 4), (21, 5), (27, 6),
    (33, 7), (40, 8), (47, 9), (55, 10), (63, 11),
)


def beaufort_from_knots(knots: float) -> int:
    """Wind speed in knots → Beaufort force. Force 12 above 63 kn."""
    for upper, force in _BEAUFORT_BOUNDS:
        if knots < upper:
            return force
    return 12


class _Circuit:
    """Stops hammering a feed that is not answering."""

    def __init__(self) -> None:
        self.failures = 0
        self.open_until = 0.0
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            return time.monotonic() >= self.open_until

    def record_success(self) -> None:
        with self.lock:
            self.failures = 0
            self.open_until = 0.0

    def record_failure(self) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= FAILURE_THRESHOLD:
                self.open_until = time.monotonic() + COOLDOWN_SECONDS
                logger.warning(
                    "weather feed unreachable %d times; falling back to climatology for %d min",
                    self.failures,
                    COOLDOWN_SECONDS // 60,
                )


_circuit = _Circuit()
_cache: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: str) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def _store(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


def _get_json(url: str, params: Dict[str, str]) -> Optional[Any]:
    """One GET, or None. Never raises — the caller has a fallback."""
    if not _circuit.allow():
        return None
    query = urllib.parse.urlencode(params, safe=",")
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "QFleet/2.0 (fleet weather alerts)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        _circuit.record_success()
        return payload
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.info("weather feed unavailable (%s): %s", url, exc)
        _circuit.record_failure()
        return None
    except (ValueError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        logger.warning("weather feed returned something unparseable: %s", exc)
        _circuit.record_failure()
        return None


def _as_series_list(payload: Any) -> List[Dict[str, Any]]:
    """
    Open-Meteo returns an object for one coordinate and a list for many.
    Normalise so the caller never has to care.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _nearest_index(times: Sequence[str], when: datetime) -> Optional[int]:
    """Index of the hourly slot closest to ``when``."""
    if not times:
        return None
    target = when.replace(tzinfo=None)
    best, best_gap = None, None
    for i, stamp in enumerate(times):
        try:
            parsed = datetime.fromisoformat(str(stamp).replace("Z", ""))
        except ValueError:
            continue
        gap = abs((parsed - target).total_seconds())
        if best_gap is None or gap < best_gap:
            best, best_gap = i, gap
    return best


def _pick(series: Dict[str, Any], field: str, index: Optional[int]) -> Optional[float]:
    values = (series.get("hourly") or {}).get(field)
    if not isinstance(values, list) or index is None or index >= len(values):
        return None
    value = values[index]
    return float(value) if isinstance(value, (int, float)) else None


def fetch_marine(points: Sequence[Tuple[float, float]], when: Optional[datetime] = None):
    """
    Live sea state at each ``(lat, lon)``, in order.

    Returns a list the same length as ``points``; an entry is ``None`` where
    the feed had nothing for it. Returns ``None`` for the whole call when the
    feed is unreachable, which is the caller's signal to use the climatology.
    """
    if not points:
        return []
    when = when or datetime.now(timezone.utc)

    lats = ",".join(f"{lat:.3f}" for lat, _ in points)
    lons = ",".join(f"{lon:.3f}" for _, lon in points)
    key = f"marine:{lats}|{lons}|{when.strftime('%Y%m%d%H')}"
    hit = _cached(key)
    if hit is not None:
        return hit

    marine = _as_series_list(
        _get_json(
            MARINE_URL,
            {
                "latitude": lats,
                "longitude": lons,
                "hourly": "wave_height,swell_wave_height,wind_wave_height,wave_period",
                "timezone": "UTC",
                "forecast_days": "1",
            },
        )
    )
    wind = _as_series_list(
        _get_json(
            FORECAST_URL,
            {
                "latitude": lats,
                "longitude": lons,
                "hourly": "wind_speed_10m,wind_gusts_10m",
                "wind_speed_unit": "kn",
                "timezone": "UTC",
                "forecast_days": "1",
            },
        )
    )

    # Wave data is the point of the exercise; wind alone is not enough to
    # claim an observed sea state, so treat a missing marine body as failure.
    if not marine:
        return None

    out: List[Optional[Dict[str, Any]]] = []
    for i in range(len(points)):
        m = marine[i] if i < len(marine) else None
        w = wind[i] if i < len(wind) else None
        if not m:
            out.append(None)
            continue
        m_index = _nearest_index((m.get("hourly") or {}).get("time") or [], when)
        w_index = _nearest_index((w.get("hourly") or {}).get("time") or [], when) if w else None

        wave = _pick(m, "wave_height", m_index)
        if wave is None:
            out.append(None)
            continue

        knots = _pick(w, "wind_speed_10m", w_index) if w else None
        gust = _pick(w, "wind_gusts_10m", w_index) if w else None
        out.append(
            {
                "wave_height_m": round(wave, 2),
                "swell_height_m": _round_or_none(_pick(m, "swell_wave_height", m_index)),
                "wind_wave_height_m": _round_or_none(_pick(m, "wind_wave_height", m_index)),
                "wave_period_s": _round_or_none(_pick(m, "wave_period", m_index)),
                "wind_knots": _round_or_none(knots),
                "wind_gust_knots": _round_or_none(gust),
                # Beaufort from measured wind where we have it; otherwise from
                # the wave height, which is the scale's other half.
                "beaufort": beaufort_from_knots(knots) if knots is not None
                else _beaufort_from_wave(wave),
                "beaufort_basis": "wind" if knots is not None else "wave height",
            }
        )

    _store(key, out)
    return out


def _round_or_none(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def _beaufort_from_wave(wave_m: float) -> int:
    """Inverse of the WMO sea-state band, for when wind is missing."""
    bands = ((0.1, 1), (0.2, 2), (0.6, 3), (1.0, 4), (2.0, 5), (3.0, 6),
             (4.0, 7), (5.5, 8), (7.0, 9), (9.0, 10), (11.5, 11))
    for upper, force in bands:
        if wave_m <= upper:
            return force
    return 12


def feed_status() -> Dict[str, Any]:
    """What the alert payload reports about where its numbers came from."""
    with _circuit.lock:
        failures = _circuit.failures
        cooling = time.monotonic() < _circuit.open_until
    return {
        "provider": "Open-Meteo",
        "attribution": ATTRIBUTION,
        "reachable": not cooling,
        "consecutive_failures": failures,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }


def reset_for_tests() -> None:  # pragma: no cover - test helper
    _circuit.__init__()
    with _cache_lock:
        _cache.clear()
