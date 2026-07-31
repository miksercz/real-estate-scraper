# agents.md

## Overview

This repository, **real-estate-scraper**, contains a Python based web‑scraping tool that extracts real‑estate listings from various websites and stores the data in a structured format (CSV/JSON). The primary purpose is to provide a reusable, extensible scraper that can be easily customized for new sources.

## Contribution Notes

- **Use the local `venv`** – activate the virtual environment with `source venv/bin/activate` before installing dependencies or running the scraper. The `venv/` directory is part of the repository but should be **excluded via .gitignore**.

- **Never commit secrets** – API keys, tokens, database passwords, or any other credentials must never be added to the repository. Store them in environment variables or a `.env` file that is listed in `.gitignore`.
- **Ask before committing large changes** – Open a pull request or discuss the change with the maintainer before pushing substantial modifications, especially those that affect the scraping logic or data schema.
- **Follow the coding style** – Use `black` and `flake8` for formatting and linting. Run `make lint` (or `ruff`) locally before submitting a PR.
- **Write tests** – Add or update unit tests for any new feature or bug‑fix. The test suite lives in the `tests/` directory and can be executed with `pytest`.
- **Document new features** – Update the README and this `agents.md` file when you introduce new scraping targets, configuration options, or usage patterns.
- **Keep the repository clean** – Remove any generated files, caches, or temporary data before committing. Ensure `git status` shows only intended changes.
- **Review dependencies** – When adding new Python packages, verify they are necessary and add them to `requirements.txt` (or `pyproject.toml`).
- **Security considerations** – Respect the target site’s `robots.txt` and rate‑limit your requests. Do not perform aggressive crawls that could be interpreted as a denial‑of‑service attack.

- **Verification rule** – Try it yourself and verify. Do not ask me to check unless you have verified yourself.
- **Verification rule** – Try it yourself and verify. Do not ask me to check unless you have verified yourself.
- **Success criteria** – CSV must contain more than just the header (at least two lines). If fewer than two lines, treat as a failure.
---

*This file is intended for LLM agents (and human developers) to quickly understand the repository’s purpose and safe contribution practices.*
