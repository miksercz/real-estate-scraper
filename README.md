# Real Estate Scraper

A Python service that scrapes Czech real‑estate portals, stores listings in SQLite, and generates static HTML reports.

## Quick start (once the repo is created)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn real_estate_scraper.main:app --host 0.0.0.0 --port 8000 --reload
```

## Repository location
The repo lives at `~/git/real-estate-scraper` on your **ThinkPad X270** machine.

## Running on the ThinkPad X270 (local development)
- Ensure you have Python 3.11+ installed (`apt install python3.11-venv` on Ubuntu).
- The app now listens on **all interfaces** (`0.0.0.0:8000`). This allows other devices on your internal network to reach it directly, e.g., `http://x270.local:8000/health`.
- All scrapers use plain HTTP requests; no external services are required beyond internet access.

## Exposing the service externally
The service can be made reachable from the internet by routing traffic through the existing OpenVPN tunnel to the public VPS `mikser.cz`. The VPN is already configured, so once the tunnel is up the VPS can forward requests to the X270 on port 8000 (optionally via a reverse‑proxy).

## Project Structure
```
real_estate_scraper/
├─ real_estate_scraper/
│  ├─ __init__.py
│  ├─ main.py          # FastAPI entry point
│  ├─ models/
│  │   └─ listing.py   # SQLModel definition
│  ├─ scrapers/
│  │   └─ sreality.py  # scraper for sreality.cz (plug‑and‑play)
│  ├─ templates/
│  │   └─ report.html  # Jinja2 template for the generated page
│  └─ static/          # optional static assets (CSS, images)
└─ pyproject.toml
```

## Next steps
1. Push this scaffold to the private GitHub repo.
2. Implement the `sreality` scraper (ticket #3).
3. Add additional scrapers, validation, and report generation.
4. Verify OpenVPN connectivity and (optionally) configure a reverse‑proxy on the VPS.
