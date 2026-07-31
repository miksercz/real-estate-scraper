# Project Tickets (MVP Prioritized)

| # | Ticket | Description | Status |
|---|--------|-------------|--------|
| 1 | **Sreality.cz scraper** | Implement full scraping logic for `sreality.cz` – pagination, detail page parsing, private‑garden detection, and store results in the database. | To Do |
| 2 | **Baseline HTTP generation** | Create a Jinja2 template and a routine that renders filtered listings to a static `latest.html` file. | To Do |
| 3 | **FastAPI report endpoint** | Add a route (`/report`) that serves the generated `latest.html` via `FileResponse`. | To Do |
| 4 | **Project scaffolding** | Initialise repository, add `pyproject.toml`, basic FastAPI app, SQLite model, and placeholder scraper. | Done |
| 5 | **Listing model** | Define a source‑agnostic `Listing` SQLModel (already added). | Done |
| 6 | **Manual scrape endpoint** | Implement `/scrape` POST endpoint that runs all scrapers, validates listings, and regenerates the report. | To Do |
| 7 | **Listing validation** | Periodically re‑fetch stored listings to verify they still exist and capture any updates (price changes, posting date). | To Do |
| 8 | **Filtering engine** | Build reusable query helpers to filter listings by price range, location, garden type, posting age, etc. | To Do |
| 9 | **Scraper – Bezrealitky.cz** | Add a scraper for `bezrealitky.cz` following the same interface as the Sreality scraper. | To Do |
|10| **Scraper – Reality.idnes.cz** | Implement Playwright‑based scraper for the JS‑heavy site `reality.idnes.cz`. | To Do |
|11| **OpenVPN tunnelling note** | Ensure the service can be accessed via the existing OpenVPN tunnel to the public VPS `mikser.cz`. Documentation already in README. | Done |
|12| **Dockerisation (optional)** | Provide a multi‑stage Dockerfile to run the app and (optionally) the Playwright browsers. | To Do |
|13| **Systemd service** | Create a systemd unit on the X270 to keep the FastAPI server (and optional OpenVPN client) running. | To Do |
|14| **Testing suite** | Write pytest tests for each scraper (using saved HTML fixtures) and for the FastAPI endpoints. | To Do |
|15| **CI/CD pipeline** | Configure GitHub Actions to run tests, build the Docker image, and optionally push to a container registry. | To Do |
|16| **Active listing protection** | Ensure only listings with rendered `<a href="/detail/...">` links are saved, skipping inactive ones. | Done |
