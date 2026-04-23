# Troubleshooting

## Server Starts But State Looks Empty or Ephemeral

Check whether you are running with a persistent `OASIS_DB_PATH`. Container deployments are expected to set it; local development may otherwise use startup-created SQLite files.

## `pytest` Fails Due To Missing Native Libraries

Install the system packages used by CI:

```bash
sudo apt-get update
sudo apt-get install -y libcairo2-dev pkg-config libigraph-dev
```

## API Health Is Up But Branch Behavior Is Wrong

Check:

- whether the change affected a branch service but only the route layer was tested
- whether the request/response contract drifted from `mitosis-prototype` expectations
- whether branch database initialization changed in `oasis/api.py`

## Workflow Drift From Shared CI Contract

Because OASIS uses an inlined workflow, compare `.github/workflows/ci.yml` against `mitosis-cicd` whenever:

- a shared secret name changes
- runner assumptions change
- the GHCR or deploy contract changes

## Dashboard Or Websocket Issues

Check:

- `/api/health`
- `/dashboard`
- `/ws/events`
- observatory router or event bus changes in `oasis/observatory/`
