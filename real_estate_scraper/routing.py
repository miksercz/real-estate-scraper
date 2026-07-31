"""Commute estimates to a fixed reference point using real road routing.

Car distance and time come from the OSRM public router (free, keyless) over
the real road network. Public-transport times are estimated from that road
distance with a calibrated model (walk + wait + ride + a transfer penalty
when the route crosses the centre); a naive straight-line estimate badly
understates real transit times, so the road distance is used instead.

Results are cached on disk keyed by the listing point so re-rendering a
report is offline.
"""

import json
import time
from pathlib import Path

import requests

from .filters import haversine_km

# Můstek metro (lines A + B) – the reference point for commute estimates.
MUSTEK = (50.0833, 14.4256)

_OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
_UA = "real-estate-scraper/0.1 (commute estimates)"
# OSRM returns traffic-free durations – apply a congestion buffer.
_CAR_FACTOR = 1.3
# Commercial transit speed incl. stops (bus/tram/metro mix).
_TRANSIT_SPEED_KMH = 18.0
_WALK_MIN = 8.0
_WAIT_MIN = 6.0
# A metro/tram transfer is typical once the road route crosses the centre.
_TRANSFER_THRESHOLD_KM = 10.0
_TRANSFER_MIN = 6.0
# Straight-line fallback used when OSRM is unreachable.
_ROAD_FACTOR = 1.25
_FALLBACK_CAR_KMH = 30.0

# Be gentle with the shared public OSRM instance.
_OSRM_SLEEP_S = 0.15


class Routing:
    """Per-point commute estimates to ``MUSTEK`` with on-disk caching."""

    def __init__(self, cache_path: Path | None = None):
        self.cache_path = cache_path
        self.cache: dict[str, dict] = {}
        if cache_path is not None and cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.cache = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _UA})

    def estimate(self, lat, lon) -> dict | None:
        """Estimated distance and commute times to Můstek from a point."""
        if not lat or not lon:
            return None
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        key = f"{lat:.6f},{lon:.6f}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        result = self._osrm_estimate(lat, lon)
        if result is None:
            result = self._fallback_estimate(lat, lon)
        self.cache[key] = result
        if self.cache_path is not None:
            self._save()
        return result

    def _osrm_estimate(self, lat: float, lon: float) -> dict | None:
        url = f"{_OSRM_URL}/{lon},{lat};{MUSTEK[1]},{MUSTEK[0]}?overview=false"
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            route = resp.json()["routes"][0]
            time.sleep(_OSRM_SLEEP_S)
        except (requests.RequestException, KeyError, IndexError, ValueError):
            return None
        km = route["distance"] / 1000.0
        return self._compose(km, route["duration"] / 60.0)

    def _fallback_estimate(self, lat: float, lon: float) -> dict:
        road = haversine_km(lat, lon, *MUSTEK) * _ROAD_FACTOR
        car_raw = road / _FALLBACK_CAR_KMH * 60.0
        return self._compose(road, car_raw)

    def _compose(self, road_km: float, car_raw_min: float) -> dict:
        car = round(car_raw_min * _CAR_FACTOR)
        ride = road_km / _TRANSIT_SPEED_KMH * 60.0
        transfer = _TRANSFER_MIN if road_km > _TRANSFER_THRESHOLD_KM else 0.0
        transit = round(_WALK_MIN + _WAIT_MIN + ride + transfer)
        return {"dist_km": round(road_km, 1), "car_min": car, "transit_min": transit}

    def _save(self) -> None:
        try:
            self.cache_path.write_text(json.dumps(self.cache), encoding="utf-8")
        except OSError:
            pass
