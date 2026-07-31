"""Entry point for the real_estate_scraper package.

Usage example:
    python -m real_estate_scraper --output listings.csv --limit 100
"""

import argparse
from pathlib import Path

from .scraper import SrealityScraper


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sreality.cz scraper – output CSV")
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
        help="Maximum number of listings to fetch (default: all)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between page requests (default: 1.0)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scraper = SrealityScraper(output_path=args.output, limit=args.limit, delay=args.delay)
    scraper.run()
    print(f"Scraping finished – data saved to {args.output}")


if __name__ == "__main__":
    main()
