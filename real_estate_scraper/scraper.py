"""Scraper core for sreality.cz.

Provides a simple synchronous implementation that fetches listing pages,
parses basic fields (price, address, description, url) using the JSON
data embedded in the page (the __NEXT_DATA__ script), and writes the
results to a CSV file.
"""

import csv
import json
import time
from pathlib import Path
from typing import List, Dict

import requests
from bs4 import BeautifulSoup


class BaseScraper:
    """Abstract base class – concrete subclasses must implement
    ``list_page_url`` and ``parse_listing``.
    """

    def __init__(self, output_path: Path, limit: int | None = None, delay: float = 1.0):
        self.output_path = output_path
        self.limit = limit
        self.delay = delay
        self.session = requests.Session()

    def fetch(self, url: str) -> str:
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        return resp.text

    def list_page_url(self, page: int) -> str:
        raise NotImplementedError

    def parse_listing(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        raise NotImplementedError

    def run(self) -> None:
        """Iterate over pagination until ``limit`` is reached or no more pages.
        Results are written incrementally to the CSV file.
        """
        fieldnames = ["price", "address", "description", "url"]
        with self.output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            page = 1
            total = 0
            while True:
                url = self.list_page_url(page)
                html = self.fetch(url)
                soup = BeautifulSoup(html, "html.parser")
                listings = self.parse_listing(soup)
                if not listings:
                    break
                for listing in listings:
                    writer.writerow(listing)
                    total += 1
                    if self.limit and total >= self.limit:
                        return
                page += 1
                time.sleep(self.delay)


class SrealityScraper(BaseScraper):
    """Concrete scraper for https://www.sreality.cz.
    The site lists 30 items per page under the `/hledani/` endpoint.
    This implementation extracts a minimal set of fields.
    """

    BASE_URL = "https://www.sreality.cz"
    SEARCH_PATH = "/hledani"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def list_page_url(self, page: int) -> str:
        # sreality uses a query parameter `page=` for pagination.
        return f"{self.BASE_URL}{self.SEARCH_PATH}?page={page}"

    def parse_listing(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        import re as _re
        # Extract the embedded JSON payload from the Next.js script tag.
        script_tag = soup.find("script", {"id": "__NEXT_DATA__", "type": "application/json"})
        if not script_tag:
            return []
        try:
            data = json.loads(script_tag.string)
        except json.JSONDecodeError:
            return []
        # The listings are stored inside the dehydrated state's queries where queryKey[0] == 'estatesSearch'.
        queries = data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
        items = []
        for q in queries:
            if isinstance(q.get('queryKey'), list) and q['queryKey'] and q['queryKey'][0] == 'estatesSearch':
                items = q.get('state', {}).get('data', {}).get('results', [])
                break

        # Build a map of item ID -> canonical URL from the <a href="/detail/..."> tags
        # that the site itself renders. Only listings with a rendered link are active.
        id_to_href: Dict[str, str] = {}
        for a_tag in soup.find_all('a', href=_re.compile(r'^/detail/')):
            href = a_tag['href']
            # The ID is the last path segment: /detail/prodej/byt/3+1/city/123456
            segments = href.rstrip('/').split('/')
            if segments:
                id_to_href[segments[-1]] = self.BASE_URL + href

        results = []
        for item in items:
            item_id = str(item.get('id', ''))
            # Only include listings that have a rendered link on the page.
            url = id_to_href.get(item_id, '')
            if not url:
                continue
            # Price in CZK
            price = str(item.get('priceCzk', ''))
            # Build address from locality when available, fall back to name.
            address = item.get('name', '')
            loc = item.get('locality', {})
            city = loc.get('city')
            street = loc.get('street')
            number = loc.get('streetNumber')
            if city and street:
                address = f"{city}, {street} {number or ''}".strip()
            description = ''
            results.append({
                "price": price,
                "address": address,
                "description": description,
                "url": url,
            })
        return results

