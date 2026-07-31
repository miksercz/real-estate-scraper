"""FastAPI application exposing the scraper over HTTP.

Endpoints
---------
``GET /``
    Service overview (name, version, available endpoints).
``GET /report``
    Serves the latest generated HTML report via ``FileResponse``.
``POST /scrape``
    Runs the sreality.cz scraper with the given filter options, writes
    the CSV, regenerates the HTML report and returns a summary.
"""

from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .filters import Filters, resolve_center
from .report import render_report
from .scraper import SrealityScraper

app = FastAPI(
    title="real-estate-scraper",
    version="0.1.0",
    description="Scrapes real-estate listings and serves an HTML report.",
)


def _scraper_class(source: str):
    if source == "bezrealitky":
        from .bezrealitky import BezrealitkyScraper

        return BezrealitkyScraper
    return SrealityScraper


class ScrapeRequest(BaseModel):
    """Mirror of the CLI options for a single scrape run."""

    source: str = "sreality"
    output: Path = Path("sreality_listings.csv")
    report: Path = Path("latest.html")
    limit: int | None = Field(None, ge=1)
    delay: float = Field(1.0, gt=0)
    category: str | None = None
    locality: str | None = None
    min_price: int | None = Field(None, ge=0)
    max_price: int | None = Field(None, ge=0)
    min_area: int | None = Field(None, ge=0)
    max_area: int | None = Field(None, ge=0)
    rooms: str | None = None
    min_rooms: int | None = Field(None, ge=1)
    garden: bool = False
    since_days: int = Field(30, ge=0)
    center: str | None = None
    radius: float | None = Field(None, gt=0)
    detail_limit: int = Field(100, ge=1)
    render_html: bool = True


@app.get("/")
def index() -> dict:
    return {
        "name": "real-estate-scraper",
        "version": app.version,
        "endpoints": ["GET /report", "POST /scrape"],
    }


@app.get("/report")
def get_report() -> FileResponse:
    path = Path("latest.html")
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="No report generated yet – POST /scrape first",
        )
    return FileResponse(path, media_type="text/html")


@app.post("/scrape")
def scrape(req: ScrapeRequest) -> dict:
    if (req.center is None) != (req.radius is None):
        raise HTTPException(
            status_code=422,
            detail="center and radius must be used together",
        )
    try:
        center = resolve_center(req.center) if req.center else None
    except (ValueError, requests.RequestException) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filters = Filters(
        min_price=req.min_price,
        max_price=req.max_price,
        min_area=req.min_area,
        max_area=req.max_area,
        rooms=tuple(r.strip() for r in (req.rooms or "").split(",") if r.strip()),
        min_rooms=req.min_rooms,
        garden=req.garden,
        since_days=req.since_days,
        center=center,
        radius_km=req.radius,
        detail_limit=req.detail_limit,
    )
    scraper = _scraper_class(req.source)(
        output_path=req.output,
        limit=req.limit,
        delay=req.delay,
        category=req.category or "",
        localities=[s for s in (req.locality or "").split(",") if s],
        filters=filters,
        enrich=req.render_html,
    )
    try:
        scraper.run()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Scrape failed: {exc}") from exc
    if req.render_html:
        render_report(req.report, scraper.rows, cache_path=Path("commute_cache.json"))
    return {
        "listings": len(scraper.rows),
        "output": str(req.output),
        "report": str(req.report) if req.render_html else None,
    }
