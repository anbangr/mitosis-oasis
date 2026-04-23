# Development

## Prerequisites

- Python 3.10 or 3.11
- system packages required by CI and local builds for graph/visualization support:
  - `libcairo2-dev`
  - `pkg-config`
  - `libigraph-dev`

## Local Setup

Preferred local workflow:

```bash
poetry install
uvicorn oasis.api:app --host 0.0.0.0 --port 8000 --reload
```

CI-compatible install path:

```bash
python -m pip install --upgrade pip
pip install -e .
```

## Daily Commands

```bash
pytest -v
uvicorn oasis.api:app --host 0.0.0.0 --port 8000 --reload
```

## Runtime Notes

- Local server default is `http://localhost:8000`.
- Container deployments set `OASIS_DB_PATH=/app/data/governance.db` so the platform can persist database-backed state on disk.
- The FastAPI lifespan also creates branch-specific SQLite databases at startup for governance, execution, adjudication, and observatory services.

## Development Rules

- Treat the HTTP contract as the stable boundary other repos depend on.
- If a change alters a route, request/response contract, or health behavior, update `docs/api.md`, `docs/testing.md`, and downstream consumer docs together.
- If a change only affects the public docs site, keep the internal engineering docs untouched unless engineering behavior changed too.
