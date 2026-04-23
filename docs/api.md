# API Surface

This page summarizes the contracts other repos care about most.

## Primary Surfaces

| Surface | Purpose |
|---|---|
| REST endpoints under `/api/...` | platform actions, health, branch-specific operations |
| Versioned routers | governance, execution, adjudication, observatory branch APIs |
| `/ws/events` | observatory realtime stream |
| `/dashboard` | operator-facing observatory dashboard |

## Cross-Repo Consumers

| Consumer | Dependency |
|---|---|
| `mitosis-prototype` | HTTP platform adapter contract and health behavior |
| `mitosis-control-plane` | platform registry, health checks, and observatory access |

## Contract Change Rule

If a route change affects:

- health endpoint behavior
- branch payload shape
- observatory outputs
- websocket event shape

then update downstream docs and tests in the same change window.
