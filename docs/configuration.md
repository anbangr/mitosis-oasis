# Configuration

## Runtime Variables

| Variable | Purpose |
|---|---|
| `OASIS_DB_PATH` | Persistent SQLite path for deployed runs |
| `PORT` | Not currently used by `oasis/server.py`; local entrypoint defaults to port `8000` via uvicorn |

## Configuration Rules

- If a new variable affects the HTTP contract or deployment behavior, document it here and in `docs/cicd.md`.
- Secret values should never be committed to the repo.
- If a new live deployment target is introduced, document the target and required variables in both this file and `docs/operations.md`.
