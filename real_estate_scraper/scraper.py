"""Scraper core for sreality.cz.

Two-pass scraping pipeline:

1. Search-result pages are crawled and parsed for cheap list-level
   fields (price, city, rooms/area extracted from the listing title).
   Candidates are filtered locally without extra requests, after the
   search URL itself has already been narrowed by deal type, main
   category and locality.

2. When the requested filters need data only present on the detail
   page (garden, posting date, energy rating), a detail page is fetched
   for each surviving candidate (up to ``detail_limit``) and the listing
   is either enriched and saved or dropped.
"""

import csv
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .districts import localities_near
from .filters import Filters, normalize_locality, parse_area, parse_rooms

# A realistic browser User-Agent avoids trivial bot detection.
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# Back off instead of hammering when the site asks us to slow down.
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRIES = 3
_RETRY_BASE_SLEEP = 5.0


class BaseScraper:
    """Base class – concrete subclasses must implement ``list_page_url``,
    ``parse_listing`` and ``parse_detail``.
    """

    SOURCE = "sreality"

    def __init__(
        self,
        output_path: Path,
        limit: int | None = None,
        delay: float = 1.0,
        filters: Filters | None = None,
        enrich: bool = False,
    ):
        self.output_path = output_path
        self.limit = limit
        self.delay = delay
        self.filters = filters or Filters()
        self.enrich = enrich
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _BROWSER_UA})
        self.pagination = None
        self._root = ""
        self.rows = []
        self.fieldnames = [
            "id",
            "source",
            "price",
            "rooms",
            "room_count",
            "area",
            "city",
            "address",
            "garden",
            "since",
            "energy",
            "url",
            "lat",
            "lon",
            "image",
        ]

    def fetch(self, url: str) -> str:
        resp = None
        for attempt in range(_RETRIES):
            resp = self.session.get(url, timeout=10)
            if resp.status_code not in _RETRY_STATUSES:
                break
            time.sleep(_RETRY_BASE_SLEEP * (2**attempt))
        assert resp is not None
        resp.raise_for_status()
        return resp.text

    def list_page_url(self, page: int) -> str:
        raise NotImplementedError

    def parse_listing(self, soup: BeautifulSoup) -> list[dict]:
        raise NotImplementedError

    def parse_detail(self, html: str) -> dict:
        raise NotImplementedError

    def fetch_listings(self, page: int) -> tuple[list[dict], int | None]:
        """Fetch and parse one list page.

        Returns ``(listings, total_count)``. ``total_count`` (when known)
        drives pagination through ``_at_last_page``. The default
        implementation pages over the plain HTML ``list_page_url``; API-
        based sources override this method instead.
        """
        html = self.fetch(self.list_page_url(page))
        soup = BeautifulSoup(html, "html.parser")
        return self.parse_listing(soup), None

    def _list_matches(self, listing: dict) -> bool:
        """List-tier filter applied to every candidate.

        Sources that expose detail-level fields directly on the list page
        may override this to run the detail tier as well.
        """
        return self.filters.list_matches(listing)

    def _at_last_page(self, page: int) -> bool:
        """True when the server-reported total says there are no more pages."""
        total = self.pagination.get("total") if self.pagination else None
        per_page = self.pagination.get("limit") if self.pagination else None
        if total is None or not per_page:
            return False
        return page * per_page >= total

    def _needs_details(self) -> bool:
        """True when detail pages must be fetched (filtering or enrichment)."""
        return self.filters.has_detail_filters() or self.enrich

    def _candidate_cap(self) -> int | None:
        """Max candidates to collect on list pages before the detail pass.

        When detail filters are active we collect a generous pool, because
        the site's sort order is by last activity, not posting date, so
        ``limit`` can only bound the number of listings saved after the
        detail pass runs.
        """
        if self._needs_details():
            return self.filters.detail_limit * 10
        return self.limit

    def search_roots(self) -> list[str]:
        """Search-path roots to crawl, one per locality."""
        return [""]

    def run(self, write_csv: bool = True) -> None:
        """Scrape, filter, enrich and write the CSV.

        ``write_csv=False`` skips the file write so a caller can combine
        several sources into one CSV/report; the ``source`` field is still
        stamped onto every row.
        """
        per_root: list[tuple[str, list[dict]]] = []
        seen_ids = set()
        cap = self._candidate_cap()
        for root in self.search_roots():
            self._root = root
            candidates = []
            page = 1
            while True:
                if cap and len(candidates) >= cap:
                    break
                try:
                    listings, _total = self.fetch_listings(page)
                except requests.HTTPError:
                    # A source may 404 past a fixed pagination depth – treat as end.
                    break
                if not listings:
                    break
                for listing in listings:
                    if not self._list_matches(listing):
                        continue
                    if listing["id"] in seen_ids:
                        continue
                    seen_ids.add(listing["id"])
                    candidates.append(listing)
                    if cap and len(candidates) >= cap:
                        break
                if self._at_last_page(page):
                    break
                page += 1
                time.sleep(self.delay)
            per_root.append((root, candidates))

        rows = []
        if self._needs_details():
            # Each locality gets its own detail budget so a single
            # district cannot starve the others during a radius search.
            for _root, candidates in per_root:
                if self.limit and len(rows) >= self.limit:
                    break
                for fetched, listing in enumerate(candidates):
                    if fetched >= self.filters.detail_limit:
                        break
                    if self.limit and len(rows) >= self.limit:
                        break
                    detail = self._fetch_detail(listing)
                    merged = {**listing, **(detail or {})}
                    # detail_matches drops unverifiable listings when detail
                    # filters are active; enrichment alone keeps them.
                    if self.filters.detail_matches(merged):
                        rows.append(merged)
        else:
            rows = []
            for _root, candidates in per_root:
                if self.limit and len(rows) >= self.limit:
                    break
                rows.extend(candidates)
        self.rows = rows
        for row in rows:
            row["source"] = self.SOURCE
        if not write_csv:
            return

        with self.output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in self.fieldnames})

    def _fetch_detail(self, listing: dict) -> dict:
        try:
            html = self.fetch(listing["url"])
        except requests.RequestException:
            return {}
        detail = self.parse_detail(html)
        time.sleep(self.delay)
        return detail


class SrealityScraper(BaseScraper):
    """Concrete scraper for https://www.sreality.cz.
    The site lists 22 items per page under the `/hledani/` endpoint and
    filters can be pushed into the URL path.
    """

    BASE_URL = "https://www.sreality.cz"
    SEARCH_PATH = "/hledani"

    DEAL_TYPES = ("prodej", "pronajem", "drazba", "vymena")
    MAIN_CATEGORIES = ("byty", "domy", "pozemky", "komercni", "ostatni")

    def __init__(
        self,
        *args,
        category: str = "",
        localities: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.category = self._validate_category(category)
        self.localities = [normalize_locality(s) for s in (localities or []) if s]
        # A radius around a center without explicit localities expands to
        # the districts whose territory could intersect the circle.
        if (
            not self.localities
            and self.filters.center is not None
            and self.filters.radius_km is not None
        ):
            self.localities = localities_near(
                self.filters.center, self.filters.radius_km
            )

    def _validate_category(self, category: str) -> str:
        segments = [s for s in category.split("/") if s]
        for seg in segments:
            if seg not in self.DEAL_TYPES and seg not in self.MAIN_CATEGORIES:
                raise ValueError(
                    f"Unknown category segment '{seg}' – expected one of "
                    f"{self.DEAL_TYPES} or {self.MAIN_CATEGORIES}"
                )
        return "/".join(segments)

    def search_roots(self) -> list[str]:
        """One search path per locality (or a country-wide search if none)."""
        roots = []
        for locality in self.localities:
            path = self.SEARCH_PATH
            if self.category:
                path += "/" + self.category
            if locality:
                path += "/" + locality
            roots.append(path)
        return roots or [
            self.SEARCH_PATH + (f"/{self.category}" if self.category else "")
        ]

    def list_page_url(self, page: int) -> str:
        # sreality paginates with ?strana=N (Czech for "page").
        return f"{self.BASE_URL}{self._root}?strana={page}"

    def parse_listing(self, soup: BeautifulSoup) -> list[dict]:
        # Extract the embedded JSON payload from the Next.js script tag.
        script_tag = soup.find(
            "script", {"id": "__NEXT_DATA__", "type": "application/json"}
        )
        if not script_tag:
            return []
        try:
            data = json.loads(script_tag.string)
        except json.JSONDecodeError:
            return []
        # The listings live in the dehydrated state's queries where queryKey[0] == 'estatesSearch'.
        queries = (
            data.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [])
        )
        items = []
        for q in queries:
            if (
                isinstance(q.get("queryKey"), list)
                and q["queryKey"]
                and q["queryKey"][0] == "estatesSearch"
            ):
                state_data = q.get("state", {}).get("data", {})
                items = state_data.get("results", [])
                self.pagination = state_data.get("pagination") or self.pagination
                break

        # Map item ID -> canonical URL from the <a href="/detail/..."> tags that the
        # site itself renders. Only listings with a rendered link are active.
        id_to_href: dict[str, str] = {}
        for a_tag in soup.find_all("a", href=re.compile(r"^/detail/")):
            href = a_tag["href"]
            segments = href.rstrip("/").split("/")
            if segments:
                id_to_href[segments[-1]] = self.BASE_URL + href

        results = []
        for item in items:
            item_id = str(item.get("id", ""))
            url = id_to_href.get(item_id, "")
            if not url:
                continue
            name = item.get("name", "")
            loc = item.get("locality", {})
            city = loc.get("city") or loc.get("cityPart") or ""
            street = loc.get("street", "")
            number = loc.get("streetNumber")
            address = (
                f"{city}, {street} {number or ''}".strip() if city and street else name
            )
            images = item.get("images") or []
            image = images[0].get("url", "") if images else ""
            if image.startswith("//"):
                image = "https:" + image
            # The CDN 401s bare URLs – it only serves images with the
            # resize params the rendered page attaches.
            if image:
                image += "?fl=res,800,600,3|shr,,20|webp,60"
            results.append(
                {
                    "id": item_id,
                    "price": item.get("priceCzk") or "",
                    "rooms": parse_rooms(name),
                    "room_count": "",
                    "area": parse_area(name),
                    "city": city,
                    "address": address,
                    "garden": "",
                    "since": "",
                    "energy": "",
                    "url": url,
                    "lat": loc.get("latitude", ""),
                    "lon": loc.get("longitude", ""),
                    "image": image,
                }
            )
        return results

    def parse_detail(self, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        script_tag = soup.find(
            "script", {"id": "__NEXT_DATA__", "type": "application/json"}
        )
        if not script_tag:
            return {}
        try:
            data = json.loads(script_tag.string)
        except json.JSONDecodeError:
            return {}
        queries = (
            data.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [])
        )
        for q in queries:
            if (
                isinstance(q.get("queryKey"), list)
                and q["queryKey"]
                and q["queryKey"][0] == "estate"
            ):
                item = q.get("state", {}).get("data", {})
                params = item.get("params", {})
                energy = params.get("energyEfficiencyRating") or {}
                usable_area = params.get("usableArea") or item.get("usableArea")
                garden_area = params.get("gardenArea")
                room_count = params.get("roomCountCb") or {}
                if isinstance(room_count, dict):
                    room_count = room_count.get("value")
                detail = {
                    "usable_area": usable_area,
                    "garden_area": garden_area,
                    "estate_area": params.get("estateArea"),
                    "building_area": params.get("buildingArea"),
                    "room_count": room_count or "",
                    "since": params.get("since"),
                    "energy": energy.get("name", ""),
                }
                if usable_area:
                    detail["area"] = usable_area
                if garden_area:
                    detail["garden"] = garden_area
                return detail
        return {}
