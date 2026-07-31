"""HTML report generation for scraped listings.

Renders the filtered listings to a standalone ``latest.html`` file via a
Jinja2 template packaged in ``real_estate_scraper/templates/``.
"""

from collections import Counter
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader

from .routing import Routing

_SOURCE_DOMAINS = {
    "bezrealitky": "bezrealitky.cz",
    "sreality": "sreality.cz",
}


def _decorate(row: dict, routing: Routing) -> dict:
    """Add human-friendly display fields to a listing row."""
    out = dict(row)
    price = out.get("price") or ""
    if price:
        out["price_fmt"] = f"{int(price):,}".replace(",", " ") + " Kč"
    else:
        out["price_fmt"] = ""
    source = out.get("source") or ""
    out["source_domain"] = _SOURCE_DOMAINS.get(source, source)
    travel = routing.estimate(out.get("lat"), out.get("lon"))
    if travel:
        out.update(travel)
    return out


def _sort_key(row: dict):
    # Nearest to Můstek first; rows without coordinates sort last.
    return (1 if row.get("dist_km") is None else 0, row.get("dist_km") or float("inf"))


def render_report(
    output_path: Path,
    rows: list[dict],
    cache_path: Path | None = None,
) -> None:
    """Write ``output_path`` with a rendered HTML page of the given rows."""
    routing = Routing(cache_path)
    env = Environment(
        loader=PackageLoader("real_estate_scraper", "templates"),
        autoescape=True,
    )
    template = env.get_template("latest.html")
    listings = [
        _decorate(r, routing) for r in sorted(rows, key=_sort_key, reverse=False)
    ]
    source_counts = dict(
        Counter((r.get("source") or "").strip() for r in listings).most_common()
    )
    html = template.render(
        listings=listings,
        source_counts=source_counts,
        generated_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
    )
    output_path.write_text(html, encoding="utf-8")
