"""District registry for automatic radius search.

sreality searches by locality slug (city or district), so a pure "N km
around a centre" query cannot be pushed into the search URL. Instead the
scraper expands a radius request into the list of districts whose
territory could intersect the circle, searches each of them, and lets the
usual radius filter trim the results.

The registry holds the Czech districts that surround Prague. Distances are
measured from each district's centroid (geocoded via OpenStreetMap
Nominatim); the margin below covers the largest district spans so that a
district touching the circle is never skipped.
"""

from .filters import haversine_km

# sreality district slug -> (latitude, longitude) centroid.
DISTRICTS: dict[str, tuple[float, float]] = {
    "praha": (50.0874654, 14.4212535),
    "praha-zapad": (49.9984420, 14.2634283),
    "praha-vychod": (50.0828112, 14.7192179),
    "kladno": (50.1898980, 14.1156769),
    "melnik": (50.3581625, 14.5534196),
    "beroun": (49.8818150, 14.0140116),
    "benesov": (49.7077965, 14.8155533),
    "kolin": (50.0195135, 15.0890417),
    "nymburk": (50.2158560, 15.0847767),
    "mlada-boleslav": (50.4013853, 14.9295810),
    "kutna-hora": (49.8641083, 15.2111901),
    "pribram": (49.6933941, 14.1748914),
}

# Half the span of the largest Czech district (Benešov, ~50 km) – a safe
# margin so districts whose territory touches the circle are included.
_DISTRICT_MARGIN_KM = 30.0


def localities_near(center: tuple[float, float], radius_km: float) -> list[str]:
    """District slugs whose territory could intersect the radius circle."""
    lat, lon = center
    return [
        slug
        for slug, (dlat, dlon) in DISTRICTS.items()
        if haversine_km(lat, lon, dlat, dlon) <= radius_km + _DISTRICT_MARGIN_KM
    ]
