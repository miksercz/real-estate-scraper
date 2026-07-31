"""Entry point for the real_estate_scraper package.

Usage example:
    python -m real_estate_scraper --output listings.csv --limit 100
    python -m real_estate_scraper --category prodej/domy --locality praha \
        --min-price 5000000 --max-price 12000000 --garden --limit 20
    python -m real_estate_scraper --source all --category prodej/domy \
        --locality praha --min-price 5000000 --max-price 13000000 \
        --garden --html latest.html
"""

import argparse
import csv
from pathlib import Path

from .filters import Filters, resolve_center
from .report import render_report
from .scraper import SrealityScraper

_ALL_SOURCES = ("sreality", "bezrealitky")


def _scraper_class(source: str):
    if source == "bezrealitky":
        from .bezrealitky import BezrealitkyScraper

        return BezrealitkyScraper
    return SrealityScraper


def _parse_sources(raw: str) -> list[str]:
    """``--source`` value -> list of source names ("all" = every source)."""
    if raw == "all":
        return list(_ALL_SOURCES)
    sources = [s.strip() for s in raw.split(",") if s.strip()]
    unknown = [s for s in sources if s not in _ALL_SOURCES]
    if unknown:
        raise SystemExit(
            f"Unknown source(s) {', '.join(unknown)} – expected one of "
            f"{list(_ALL_SOURCES)} or 'all'"
        )
    return sources


def _write_combined_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    seen = set()
    merged = []
    for row in rows:
        key = (row.get("source", ""), row.get("id", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in merged:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reality-scraper CLI – output a filtered CSV"
    )
    parser.add_argument(
        "--source",
        default="sreality",
        help="Source(s) to scrape, comma-separated, or 'all' for every "
        "supported source (default: sreality)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("sreality_listings.csv"),
        help="Path to CSV file that will be created/overwritten",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of listings to save (default: all)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between requests (default: 1.0)",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Deal type and main category pushed into the search URL, "
        "e.g. 'prodej/domy' or 'pronajem/byty'",
    )
    parser.add_argument(
        "--locality",
        default=None,
        help="Locality SEO slug(s), comma-separated, e.g. 'praha,melnik' "
        "(also accepts 'prague'; omit to auto-expand --center/--radius "
        "into the Czech districts that could intersect the circle)",
    )
    parser.add_argument(
        "--min-price",
        type=int,
        default=None,
        help="Minimum price in CZK",
    )
    parser.add_argument(
        "--max-price",
        type=int,
        default=None,
        help="Maximum price in CZK",
    )
    parser.add_argument(
        "--min-area",
        type=int,
        default=None,
        help="Minimum usable area in m2",
    )
    parser.add_argument(
        "--max-area",
        type=int,
        default=None,
        help="Maximum usable area in m2",
    )
    parser.add_argument(
        "--rooms",
        default=None,
        help="Comma-separated room layouts, e.g. '3+1,3+kk'",
    )
    parser.add_argument(
        "--min-rooms",
        type=int,
        default=None,
        help="Only keep listings with at least this many rooms, e.g. 4 "
        "for '4+kk' and up (triggers the detail pass)",
    )
    parser.add_argument(
        "--garden",
        action="store_true",
        help="Only keep listings with a garden (requires detail fetch)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="Only keep listings posted within this many days "
        "(default: 30, use 0 to disable; requires detail fetch)",
    )
    parser.add_argument(
        "--center",
        default=None,
        help="Center point for a radius filter: 'lat,lon' (e.g. '50.0875,14.4213') "
        "or a place name resolved via OpenStreetMap (e.g. 'Prague')",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=None,
        help="Keep only listings within this many km of --center",
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=None,
        help="Also render the filtered listings to this HTML report "
        "(fetches detail pages for full details, capped by --detail-limit)",
    )
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=100,
        help="Maximum detail pages fetched when detail filters are active "
        "(default: 100)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if (args.center is None) != (args.radius is None):
        raise SystemExit("--center and --radius must be used together")
    if args.since_days is not None and args.since_days < 0:
        raise SystemExit("--since-days must be >= 0 (0 disables the date filter)")
    if args.min_rooms is not None and args.min_rooms < 1:
        raise SystemExit("--min-rooms must be >= 1")
    center = resolve_center(args.center) if args.center else None
    filters = Filters(
        min_price=args.min_price,
        max_price=args.max_price,
        min_area=args.min_area,
        max_area=args.max_area,
        rooms=tuple(r.strip() for r in (args.rooms or "").split(",") if r.strip()),
        min_rooms=args.min_rooms,
        garden=args.garden,
        since_days=args.since_days,
        center=center,
        radius_km=args.radius,
        detail_limit=args.detail_limit,
    )
    sources = _parse_sources(args.source)

    all_rows = []
    fieldnames: list[str] = []
    for source in sources:
        scraper = _scraper_class(source)(
            output_path=args.output,
            limit=args.limit,
            delay=args.delay,
            category=args.category or "",
            localities=[s for s in (args.locality or "").split(",") if s],
            filters=filters,
            enrich=args.html is not None,
        )
        if scraper.localities:
            print(f"[{source}] Localities: {', '.join(scraper.localities)}")
        scraper.run(write_csv=len(sources) == 1)
        all_rows.extend(scraper.rows)
        fieldnames = scraper.fieldnames
        print(f"[{source}] {len(scraper.rows)} listings")

    if len(sources) > 1:
        all_rows = _write_combined_csv(args.output, all_rows, fieldnames)
    print(f"Scraping finished – {len(all_rows)} listings saved to {args.output}")

    if args.html:
        render_report(args.html, all_rows, cache_path=Path("commute_cache.json"))
        print(f"Report generated – {args.html}")


if __name__ == "__main__":
    main()
