# real-estate-scraper

A lightweight Python scraper for **sreality.cz** that outputs property listings to a CSV file.

## Features (MVP)
- Synchronous scraping using `requests` and `BeautifulSoup`.
- One‑click CLI: `python -m real_estate_scraper`.
- Configurable output path, limit, and request delay.
- Active‑listing protection: URLs are extracted from rendered `<a href="/detail/...">` tags, ensuring only live listings are saved.
- No database – results are written directly to CSV.

## Installation
```bash
# Clone the repo and cd into it
git clone https://github.com/miksercz/real-estate-scraper.git
cd real-estate-scraper

# Install dependencies (pipenv recommended)
pip install -r requirements.txt
```

## Usage
```bash
python -m real_estate_scraper \
    --output listings.csv   # CSV file to write (default: sreality_listings.csv)
    --limit 200            # optional: max number of listings
    --delay 1.5            # optional: seconds between requests
```

The script will crawl `sreality.cz` pagination until the limit is reached or no more listings are found, then save the data to the specified CSV.

By default only listings **posted in the last 30 days** are kept
(`--since-days 30`). Posting dates come from the detail pass, so the
default run is a two-pass scrape (list pages + up to `--detail-limit`
detail pages). Pass `--since-days 0` for a fast list-only scrape.

### Filtering

Filters are applied in two passes:

1. **List level (cheap, no extra requests)** – price, usable area and room
   layout (parsed from the listing title, e.g. `3+1`, `2+kk`) are checked
   against each search-result page. Deal type, main category and locality
   are pushed into the search URL so the server does the heavy lifting.
2. **Detail level (one request per candidate)** – only triggered by
   `--garden` or `--since-days`; fetches each surviving candidate's detail
   page for authoritative garden, usable-area, posting-date and energy
   data, then applies the remaining filters.

```bash
# Houses for sale in Prague, 10–30M CZK, at least 150 m2
python -m real_estate_scraper \
    --category prodej/domy --locality praha \
    --min-price 10000000 --max-price 30000000 --min-area 150 --limit 20

# 3-room flats anywhere, posted within the last 30 days
python -m real_estate_scraper \
    --category prodej/byty --rooms 3+1,3+kk --since-days 30 --limit 20

# Houses with a garden, posted within the last year
python -m real_estate_scraper \
    --category prodej/domy --garden --since-days 365 --limit 20

# Anything within 20 km of Prague city centre (uses listing coordinates,
# no extra requests)
python -m real_estate_scraper \
    --locality praha --center "Prague" --radius 20 --limit 20

# Radius search without a locality list: the scraper auto-discovers the
# Czech districts that could touch the 20 km circle (Prague, Kladno,
# Mělník, ...), searches each, and the radius filter trims the results
python -m real_estate_scraper \
    --category prodej/domy --center "Prague" --radius 20 --garden --limit 20

# Also render a browsable HTML report (fetches detail pages for full
# details – garden, posting date, energy – capped by --detail-limit)
python -m real_estate_scraper \
    --category prodej/domy --locality praha --min-price 20000000 --limit 20 \
    --html latest.html
```

| Flag | Meaning |
|------|---------|
| `--source` | Source(s) to scrape: `sreality` (default), `bezrealitky`, a comma-separated list (`sreality,bezrealitky`), or `all` for every source. Multi-source runs merge into one CSV and one report |
| `--category` | Deal type + main category pushed to the URL, e.g. `prodej/domy`, `pronajem/byty` |
| `--locality` | Locality SEO slug(s), comma-separated, e.g. `praha,melnik`. Each locality is searched separately, then all filters (including radius) apply across them (also accepts `prague`). Omit it and pass `--center`/`--radius` to auto-select the Czech districts that could intersect the radius circle |
| `--min-price` / `--max-price` | Price range in CZK |
| `--min-area` / `--max-area` | Usable area range in m² |
| `--rooms` | Comma-separated room layouts, e.g. `3+1,3+kk` |
| `--min-rooms` | Only listings with at least N rooms, e.g. `4` for `4+kk` and up (triggers the detail pass; uses the authoritative room count from the detail page) |
| `--garden` | Only listings with a garden (triggers the detail pass). Counts a declared garden area, or a parcel (`estate_area`) larger than the building footprint – i.e. land beyond the building |
| `--since-days` | Only listings posted within N days (default: 30; `0` disables the date filter; triggers the detail pass) |
| `--center` | Radius centre: `lat,lon` (e.g. `50.0875,14.4213`) or a place name geocoded via OpenStreetMap (e.g. `Prague`) |
| `--radius` | Keep only listings within N km of `--center` (must be used with it) |
| `--html` | Render the filtered listings to this HTML report file |
| `--detail-limit` | Max detail pages fetched by the detail pass (default: 100) |

Detail-page columns (`garden`, `since`, `energy`) are populated when the
detail pass runs. It runs when `--garden`, `--since-days` (default 30) or
`--html` is used; `--since-days 0` disables it for fast list-only scrapes.

When the detail pass is active, `--limit` bounds how many listings are
*saved* (after filtering), not how many are collected – the scraper keeps
a larger candidate pool and fetches up to `--detail-limit` detail pages
until the limit is reached. Each locality gets its own `--detail-limit`
budget, so a radius search over several districts cannot be starved by the
first one (a multi-district run may therefore fetch up to `--detail-limit`
pages per locality).

The CSV also includes a `room_count` column (filled by the detail pass)
with the authoritative room count sreality stores per listing.

### Sources

`--source bezrealitky` searches `bezrealitky.cz` (direct-owner listings)
through its public GraphQL API instead of sreality's HTML pages:

- Every listing field is available in the search response, so there is no
  detail pass – `--garden`, `--since-days`, `--min-rooms` run without
  extra requests.
- `--locality` slugs are resolved to bezrealitky regions. All sreality
  slugs for the Prague districts and the Central-Bohemian county towns
  (e.g. `praha`, `kladno`, `melnik`, `beroun`) resolve; county slugs such
  as `praha-zapad` do not exist there and are skipped with a warning.
- `--category` accepts both sreality's plural forms (`prodej/domy`) and
  bezrealitky's singular ones (`prodej/dum`).
- Posting age is derived from the listing's `daysActive` ("12 dní").
- `--center`/`--radius` is applied to listing coordinates client-side
  (the API exposes no working radius search).

```bash
# Flats for sale in Prague, 3–10M CZK, 3+ rooms, posted within 90 days
python -m real_estate_scraper \
    --source bezrealitky --category prodej/byt --locality praha \
    --min-price 3000000 --max-price 10000000 --min-rooms 3 \
    --since-days 90 --limit 15 --html latest.html
```

### Unified report across sources

`--source all` (or `sreality,bezrealitky`) runs every requested source with
the same filters and merges the results into **one CSV and one HTML
report** – each listing carries a `source` column and a source badge in
the report, with per-source counts in the header:

```bash
# Houses for sale in Prague, 5–13M CZK, 4+ rooms, with a garden,
# posted within 120 days – across sreality.cz and bezrealitky.cz
python -m real_estate_scraper \
    --source all --category prodej/domy --locality praha \
    --min-price 5000000 --max-price 13000000 --min-rooms 4 \
    --garden --since-days 120 --limit 30 \
    --output houses.csv --html latest.html
```

`--limit` applies per source. In a multi-source run each source's `--limit`
budget is independent, so combined results may reach `--limit` × number of
sources.

### Rate limiting

- The scraper is strictly serial: one request at a time, with `--delay`
  seconds between requests (default `1.0`). At the default that is ~1
  request/second.
- Requests use a browser User-Agent, and on a `429`/`5xx` response the
  scraper backs off exponentially (5s, 10s, 20s) and retries before
  giving up.
- Keep `--delay` at `1.0` or higher for long runs. The detail pass adds
  one request per candidate, so `--detail-limit` bounds its cost.
- Respect the site's `robots.txt` and keep total request volume low.

## HTTP API

A small FastAPI app exposes the scraper over HTTP. Run it with:

```bash
uvicorn real_estate_scraper.app:app --reload
```

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service overview (name, version, endpoints) |
| `/report` | GET | Serves the generated `latest.html` via `FileResponse` (404 until a scrape runs) |
| `/scrape` | POST | Runs the scraper with the given options, writes the CSV, regenerates the HTML report, returns a summary |

`POST /scrape` accepts the same options as the CLI as JSON (e.g.
`category`, `locality`, `min-price`, `garden`, `since_days`, `center` +
`radius`, `limit`, `detail_limit`). Example:

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"category":"prodej/domy","locality":"praha","limit":20}'
```

The generated `latest.html` and any CSV output are gitignored.

### Verifying results1. **Non-empty output** – the CSV must have at least one data row:
   ```bash
   wc -l out.csv        # header + N rows
   ```
2. **Filter correctness** – spot-check a column against the filter you
   used, e.g. all prices within range:
   ```bash
   awk -F, 'NR>1 { if ($2 < 10000000 || $2 > 30000000) print "OUT OF RANGE:", $2 }' out.csv
   ```
3. **Radius check** – verify the lat/lon columns are within the requested
   distance of your center (Prague centre ≈ `50.0875,14.4213`):
   ```bash
   python - <<'EOF'
   from math import radians, sin, cos, asin, sqrt
   import csv
   clat, clon = 50.0875, 14.4213
   R = 6371.0
   for row in csv.DictReader(open("out.csv")):
       lat, lon = float(row["lat"]), float(row["lon"])
       p = lambda d: radians(d)
       a = sin(p(lat-clat)/2)**2 + cos(p(clat))*cos(p(lat))*sin(p(lon-clon)/2)**2
       km = 2*R*asin(sqrt(a))
       print(f'{row["id"]}: {km:.1f} km')
   EOF
   ```
4. **Cross-check the total** – run without `--limit` on a small query and
   compare the row count with the result count the site shows on its
   search page.

## Contributing
- **Never commit secrets** – keep API keys or credentials out of the repo.
- Open a pull request for any substantial changes.
- Follow the style guidelines (`black`, `flake8`).
- Add or update tests under `tests/` when you add new features.

---
*Generated by Antigravity AI assistant.*
