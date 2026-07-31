"""Bezrealitky.cz scraper (public GraphQL API).

Unlike sreality.cz, bezrealitky exposes every listing field through its
GraphQL endpoint, so a single query per page is enough – there is no
detail pass. ``--locality`` slugs are resolved to bezrealitky region ids
via ``regionByUri``; sreality-only county slugs such as ``praha-zapad``
have no bezrealitky counterpart and are skipped with a warning. A
``--center``/``--radius`` filter is applied client-side to listing
coordinates, since the API has no working radius search.
"""

import json
import re
import time
from datetime import datetime, timedelta

import requests

from .filters import normalize_locality
from .scraper import (
    _RETRIES,
    _RETRY_BASE_SLEEP,
    _RETRY_STATUSES,
    BaseScraper,
)

GRAPHQL_ENDPOINT = "https://api.bezrealitky.cz/graphql/"
BASE_URL = "https://www.bezrealitky.cz"

_PAGE_SIZE = 50

_OFFER_TYPES = {"prodej": "PRODEJ", "pronajem": "PRONAJEM"}
_ESTATE_TYPES = {
    "byty": "BYT",
    "byt": "BYT",
    "domy": "DUM",
    "dum": "DUM",
    "pozemky": "POZEMEK",
    "pozemek": "POZEMEK",
    "garaz": "GARAZ",
    "kancelare": "KANCELAR",
    "kancelar": "KANCELAR",
    "nebytove-prostory": "NEBYTOVY_PROSTOR",
    "nebytovy-prostor": "NEBYTOVY_PROSTOR",
    "rekreaeni-objekty": "REKREACNI_OBJEKT",
    "rekreaeni-objekt": "REKREACNI_OBJEKT",
}

# Map bezrealitky condition enums to the sreality building-condition names
# the filters and report already understand.
_CONDITION_LABELS = {
    "VERY_GOOD": "velmi dobrý",
    "GOOD": "dobrý",
    "BAD": "špatný",
    "CONSTRUCTION": "ve výstavbě",
    "PROJECT": "projekt",
    "NEW": "novostavba",
    "DEMOLITION": "na demolici",
    "BEFORE_RECONSTRUCTION": "před rekonstrukcí",
    "AFTER_RECONSTRUCTION": "po rekonstrukci",
    "AFTER_PARTIAL_RECONSTRUCTION": "po částečné rekonstrukci",
    "IN_RECONSTRUCTION": "ve výstavbě",
}

_DISPOSITION_RE = re.compile(r"DISP_(\d+)_(KK|1|IZB)")

_DAYS_RE = re.compile(r"(\d+)\s*(?:dní|dny|den)", re.IGNORECASE)

_LIST_QUERY = """query ListAdverts($offerType:[OfferType], $estateType:[EstateType], $limit:Int, $offset:Int, $order:ResultOrder, $currency:Currency, $regionId:ID, $priceFrom:Int, $priceTo:Int, $surfaceFrom:Int, $surfaceTo:Int) {
  listAdverts(offerType:$offerType, estateType:$estateType, limit:$limit, offset:$offset, order:$order, currency:$currency, regionId:$regionId, priceFrom:$priceFrom, priceTo:$priceTo, surfaceFrom:$surfaceFrom, surfaceTo:$surfaceTo) {
    totalCount
    list {
      id uri title
      descriptionByLocale(locale: CS)
      address(locale: CS)
      city(locale: CS)
      gps { lat lng }
      surface surfaceLand price currency
      disposition condition
      penb
      mainImage { url(filter: RECORD_MAIN) }
      daysActive
    }
  }
}"""


def _disposition_layout(disposition: str) -> str:
    """Turn a Disposition enum (``DISP_3_KK``) into a layout string."""
    if not disposition or disposition in ("UNDEFINED", "OSTATNI"):
        return ""
    if disposition == "GARSONIERA":
        return "garsonka"
    match = _DISPOSITION_RE.match(disposition)
    if match:
        return f"{match.group(1)}+{match.group(2).lower()}"
    return ""


def _disposition_count(disposition: str) -> int:
    match = _DISPOSITION_RE.match(disposition or "")
    return int(match.group(1)) if match else 0


def _days_active_to_since(value: str | None) -> str:
    """``daysActive`` ("12 dní") -> ISO date the listing was posted."""
    match = _DAYS_RE.match(value or "")
    if not match:
        return ""
    since = datetime.now().astimezone().date() - timedelta(days=int(match.group(1)))
    return since.isoformat()


class BezrealitkyScraper(BaseScraper):
    """Concrete scraper for https://www.bezrealitky.cz via its GraphQL API."""

    SOURCE = "bezrealitky"

    def __init__(
        self,
        *args,
        category: str = "",
        localities: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.offer_type, self.estate_type = self._validate_category(category)
        slugs = [normalize_locality(s) for s in (localities or []) if s]
        self._region_ids: dict[str, str] = {}
        self.localities = []
        for slug in slugs:
            region_id = self._resolve_region(slug)
            if region_id:
                self._region_ids[slug] = region_id
                self.localities.append(slug)
            else:
                print(f"Skipping locality '{slug}' (no matching bezrealitky region)")
        if slugs and not self.localities:
            raise ValueError(
                f"None of the given localities resolved to a bezrealitky region: "
                f"{', '.join(slugs)}"
            )

    def _validate_category(self, category: str) -> tuple[str | None, str | None]:
        segments = [s for s in category.split("/") if s]
        if not segments:
            return None, None
        offer = _OFFER_TYPES.get(segments[0])
        if offer is None:
            raise ValueError(
                f"Unknown offer segment '{segments[0]}' – expected one of "
                f"{list(_OFFER_TYPES)}"
            )
        estate = None
        if len(segments) == 2:
            estate = _ESTATE_TYPES.get(segments[1])
            if estate is None:
                raise ValueError(
                    f"Unknown estate segment '{segments[1]}' – expected one of "
                    f"{list(_ESTATE_TYPES)}"
                )
        elif len(segments) > 2:
            raise ValueError(f"Category must be 'offer/estate', got '{category}'")
        return offer, estate

    def _post(self, payload: dict) -> dict:
        resp = None
        for attempt in range(_RETRIES):
            resp = self.session.post(GRAPHQL_ENDPOINT, json=payload, timeout=30)
            if resp.status_code not in _RETRY_STATUSES:
                break
            time.sleep(_RETRY_BASE_SLEEP * (2**attempt))
        assert resp is not None
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise requests.HTTPError(f"GraphQL error: {data['errors'][0]['message']}")
        return data

    def _fetch_region(self, slug: str) -> str | None:
        query = f"{{ regionByUri(uri: {json.dumps(slug)}, locale: CS) {{ id }} }}"
        data = self._post({"query": query})
        node = (data.get("data") or {}).get("regionByUri")
        return node["id"] if node else None

    def _resolve_region(self, slug: str) -> str | None:
        if slug in _region_cache:
            return _region_cache[slug]
        region_id = self._fetch_region(slug)
        _region_cache[slug] = region_id
        return region_id

    def search_roots(self) -> list[str]:
        """One root per locality (a bezrealitky region id), or country-wide."""
        return [self._region_ids[s] for s in self.localities] or [""]

    def list_page_url(self, page: int) -> str:
        return BASE_URL

    def fetch_listings(self, page: int) -> tuple[list[dict], int | None]:
        variables = {
            "limit": _PAGE_SIZE,
            "offset": (page - 1) * _PAGE_SIZE,
            "order": "TIMEORDER_DESC",
            "currency": "CZK",
        }
        if self.offer_type:
            variables["offerType"] = [self.offer_type]
        if self.estate_type:
            variables["estateType"] = [self.estate_type]
        if self._root:
            variables["regionId"] = self._root
        if self.filters.min_price:
            variables["priceFrom"] = self.filters.min_price
        if self.filters.max_price:
            variables["priceTo"] = self.filters.max_price
        if self.filters.min_area:
            variables["surfaceFrom"] = self.filters.min_area
        if self.filters.max_area:
            variables["surfaceTo"] = self.filters.max_area

        data = self._post(
            {
                "query": _LIST_QUERY,
                "variables": variables,
                "operationName": "ListAdverts",
            }
        )
        result = (data.get("data") or {}).get("listAdverts") or {}
        total = result.get("totalCount")
        self.pagination = {"total": total, "limit": _PAGE_SIZE}
        return self.parse_listing(result.get("list") or []), total

    def parse_listing(self, adverts: list[dict]) -> list[dict]:
        results = []
        for advert in adverts:
            gps = advert.get("gps") or {}
            disposition = advert.get("disposition")
            results.append(
                {
                    "id": str(advert.get("id", "")),
                    "price": advert.get("price") or "",
                    "rooms": _disposition_layout(disposition),
                    "room_count": _disposition_count(disposition),
                    "area": advert.get("surface") or 0,
                    "city": advert.get("city") or "",
                    "address": advert.get("address") or "",
                    "garden": "",
                    "since": _days_active_to_since(advert.get("daysActive")),
                    "energy": _penb_label(advert.get("penb")),
                    "url": (
                        f"{BASE_URL}/nemovitosti-byty-domy/{advert['uri']}"
                        if advert.get("uri")
                        else f"{BASE_URL}/vypis/{advert['id']}"
                    ),
                    "lat": gps.get("lat", ""),
                    "lon": gps.get("lng", ""),
                    "image": (advert.get("mainImage") or {}).get("url", ""),
                    # Detail-tier fields; the list response already carries them.
                    "usable_area": advert.get("surface"),
                    "estate_area": advert.get("surfaceLand"),
                    "building_area": advert.get("surface"),
                    "garden_area": None,
                    "description": advert.get("descriptionByLocale") or "",
                    "building_condition": _CONDITION_LABELS.get(
                        advert.get("condition") or "", ""
                    ),
                    "name": advert.get("title") or "",
                }
            )
        return results

    def _list_matches(self, listing: dict) -> bool:
        # Every bezrealitky listing already carries the detail-tier fields,
        # so the detail filter can run without any extra requests.
        return self.filters.list_matches(listing) and self.filters.detail_matches(
            listing
        )

    def _needs_details(self) -> bool:
        return False


def _penb_label(penb: str | None) -> str:
    return "" if penb in (None, "", "UNDEFINED") else penb


_region_cache: dict[str, str | None] = {}
