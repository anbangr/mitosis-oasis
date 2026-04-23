# Observability

## Primary Signals

| Signal | Use it for |
|---|---|
| `/api/health` | fast reachability check |
| `/dashboard` | operator-facing observability |
| `/ws/events` | realtime branch event stream |
| observatory REST endpoints | summaries, leaderboard, timeseries, and debugging data |

## What To Check First

- route failure: API logs and the specific branch router
- dashboard issue: observatory router and dashboard integration
- websocket issue: event bus and `/ws/events` path

## Cross-Repo Importance

Observatory output is consumed operationally by both `mitosis-control-plane` and humans watching experiment behavior. Treat observability changes as contract changes, not cosmetic changes.
