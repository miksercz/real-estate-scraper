"""Filtering engine for scraped listings.

Filters are evaluated in two tiers that mirror the two-pass scrape
pipeline:

1. List-level filters (``Filters.list_matches``) work on fields available
   directly on the search result pages (price, city, distance from a
   center point, rooms/area parsed from the listing title). They never
   trigger additional HTTP requests.

2. Detail-level filters (``Filters.detail_matches``) work on fields that
   only exist on the individual listing detail page (garden, posting
   date, energy rating, exact usable area). They require one extra
   request per candidate listing.
"""

import math
import re
from dataclasses import dataclass
from datetime import date, datetime

import requests

# Matches room layouts embedded in listing titles: "3+1", "3+kk", "5+2" ...
_ROOMS_RE = re.compile(r"(\d+)\+(kk|\d+)", re.IGNORECASE)
# Matches the first area in the title: "Prodej bytu 3+1 65 m², Praha" -> 65
_AREA_RE = re.compile(r"(\d+)\s*m[²2]", re.IGNORECASE)
# Matches "50.0875,14.4213"
_CENTER_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

# Common English names that do not match the sreality SEO slugs.
_LOCALITY_ALIASES = {
    "prague": "praha",
}

_EARTH_RADIUS_KM = 6371.0

# sreality uses 1 CZK as the placeholder for "price on request" (na dotaz).
_PRICE_ON_REQUEST = 1

# Partial-purchase listings: "podíl 1/2", "podílu id. 1/4", "spoluvlastnictví".
# The fraction must sit next to the ownership word so cadastral numbers
# ("parcela 1234/56", "č.p. 123/45") are not mistaken for shares.
_SHARE_RE = re.compile(
    r"(?:pod[ií]l\w*|spoluvlastnic\w*)\W{0,60}\d{1,3}\s*/\s*\d{1,3}"
    r"|\d{1,3}\s*/\s*\d{1,3}\W{0,60}pod[ií]l\w*",
    re.IGNORECASE,
)
# Demolition-intent phrases. Deliberately phrase-based: "bez nutnosti
# demolic" (no demolition needed) must not match.
_DEMO_RE = re.compile(
    r"\b(?:k\s+demolici|ke\s+demolici|na\s+demolici|demoli[čc]n[íý]\w*|"
    r"možnost[íi]\s+demolice|p[řr]ed\s+demolic[íi]|"
    r"ur[čc]en[ýáé]\s+(?:k|na)\s+demolici)\b",
    re.IGNORECASE,
)
# buildingCondition values that mean the house cannot be moved into yet.
_NOT_MOVE_IN_CONDITIONS = {
    "před rekonstrukcí",
    "špatný",
    "ve výstavbě",
    "projekt",
    "rozestavěný",
    "na demolici",
    "k demolici",
    "ke demolici",
    "hrubá stavba",
}


def is_partial_share(text: str) -> bool:
    """True when the text offers a partial ownership share, not the whole."""
    return bool(text and _SHARE_RE.search(text))


def is_move_in_ready(merged: dict) -> bool:
    """True when the listing is not a demolition case nor in a state that
    blocks moving in."""
    condition = (merged.get("building_condition") or "").strip().lower()
    if condition in _NOT_MOVE_IN_CONDITIONS:
        return False
    return not _DEMO_RE.search(merged.get("description") or "")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def resolve_center(value: str) -> tuple[float, float]:
    """Resolve a ``--center`` value to (latitude, longitude).

    Accepts literal coordinates "50.0875,14.4213" or a place name that is
    geocoded once via OpenStreetMap Nominatim.
    """
    match = _CENTER_RE.match(value)
    if match:
        return float(match.group(1)), float(match.group(2))
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": value, "format": "json", "limit": 1},
        timeout=15,
        headers={"User-Agent": "real-estate-scraper/0.1 (filter center lookup)"},
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"Could not resolve center location '{value}'")
    return float(results[0]["lat"]), float(results[0]["lon"])


def parse_rooms(name: str) -> str:
    """Extract a room layout such as "3+1" or "2+kk" from a listing title."""
    match = _ROOMS_RE.search(name or "")
    return match.group(0).lower() if match else ""


def rooms_to_count(layout: str) -> int | None:
    """Room count from a layout like "4+kk" or "5+1" (kk is not a room)."""
    match = re.match(r"(\d+)\+", layout or "")
    return int(match.group(1)) if match else None


def parse_area(name: str) -> int:
    """Extract the first area in square metres from a listing title."""
    match = _AREA_RE.search(name or "")
    return int(match.group(1)) if match else 0


def normalize_locality(locality: str) -> str:
    return _LOCALITY_ALIASES.get(locality.lower(), locality.lower())


@dataclass
class Filters:
    min_price: int | None = None
    max_price: int | None = None
    min_area: int | None = None
    max_area: int | None = None
    rooms: tuple[str, ...] = ()
    min_rooms: int | None = None
    garden: bool = False
    since_days: int | None = None
    center: tuple[float, float] | None = None
    radius_km: float | None = None
    detail_limit: int = 100

    def __post_init__(self) -> None:
        self.rooms = tuple(r.lower() for r in self.rooms)
        # 0 means "no date filter" (disabled), not "posted today".
        if self.since_days == 0:
            self.since_days = None

    def has_detail_filters(self) -> bool:
        """True when filtering needs data only present on detail pages."""
        return self.garden or self.since_days is not None or self.min_rooms is not None

    def _area_ok(self, area: int) -> bool:
        return (self.min_area is None or area >= self.min_area) and (
            self.max_area is None or area <= self.max_area
        )

    def _room_count(self, layout: str, room_count: int | None) -> int | None:
        """Best-known room count: the detail value, else the title layout."""
        return room_count or rooms_to_count(layout)

    def _has_garden(self, merged: dict) -> bool:
        """True when a listing has outdoor land.

        A declared ``garden_area`` always counts. Otherwise the listing is
        treated as having a garden when the parcel (``estate_area``) is
        larger than the building footprint (``building_area``) – i.e. there
        is land beyond the building. A parcel with no declared footprint
        also counts.
        """
        if merged.get("garden_area"):
            return True
        estate = merged.get("estate_area")
        building = merged.get("building_area")
        if estate:
            return not building or estate > building
        return False

    def list_matches(self, listing: dict) -> bool:
        """Cheap filter over fields already present on the list page."""
        price = listing.get("price") or 0
        # "Price on request" (1 CZK) is not a real price.
        if price == _PRICE_ON_REQUEST:
            price = 0
        if self.min_price is not None and price < self.min_price:
            return False
        if self.max_price is not None and (not price or price > self.max_price):
            return False
        if self.rooms and listing.get("rooms") not in self.rooms:
            return False
        if self.min_rooms is not None:
            count = self._room_count(listing.get("rooms"), None)
            # Drop only layouts we can read; unknown ones are decided by
            # the detail pass where roomCountCb is authoritative.
            if count is not None and count < self.min_rooms:
                return False
        if (
            self.min_area is not None or self.max_area is not None
        ) and not self._area_ok(listing.get("area") or 0):
            return False
        if self.center is not None and self.radius_km is not None:
            lat, lon = listing.get("lat"), listing.get("lon")
            if not lat or not lon:
                return False
            if haversine_km(lat, lon, *self.center) > self.radius_km:
                return False
        return True

    def detail_matches(self, merged: dict) -> bool:
        """Filter over a listing merged with its detail-page data."""
        if self.min_rooms is not None:
            count = self._room_count(merged.get("rooms"), merged.get("room_count"))
            if not count or count < self.min_rooms:
                return False
        area = merged.get("usable_area") or merged.get("area") or 0
        if (self.min_area is not None or self.max_area is not None) and (
            not area or not self._area_ok(area)
        ):
            return False
        if self.garden and not self._has_garden(merged):
            return False
        if self.since_days is not None:
            since = merged.get("since")
            if not since:
                return False
            try:
                days = (
                    datetime.now().astimezone().date() - date.fromisoformat(since)
                ).days
            except ValueError:
                return False
            if days > self.since_days:
                return False
        return True
