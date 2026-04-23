# Operations

## Start the Service Locally

```bash
uvicorn oasis.api:app --host 0.0.0.0 --port 8000 --reload
```

## Health Checks

| Check | Path |
|---|---|
| Service health | `/api/health` |
| API docs | `/docs` |
| Dashboard | `/dashboard` |
| Websocket stream | `/ws/events` |

## Container Runtime Notes

- Docker deployments expose host port `8100` to container port `8000`.
- Persistent state for containerized runs should use `OASIS_DB_PATH=/app/data/governance.db`.

## Current Production Posture

- CI image publishing remains active.
- Automatic deploy is disabled until a new live target is assigned.
- Any manual production bring-up should be documented back into `docs/cicd.md` and this file the same day.

## Rollback

If a future deploy target is re-enabled:

1. roll back the image tag or application commit
2. validate `/api/health`
3. validate at least one branch-specific route
4. validate dashboard or websocket behavior if the change touched observability
