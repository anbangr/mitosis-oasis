# Architecture

`mitosis-oasis` is the HTTP simulation platform used by Mitosis to emulate AgentCity-like governance behavior for external agents and experiment runners.

## Runtime Shape

```text
External agents / prototype adapter
  -> FastAPI app (`oasis.api:app`)
     -> governance router
     -> execution router
     -> adjudication router
     -> observatory router + dashboard + websocket
     -> Platform + Channel core
     -> SQLite-backed branch state
```

## Major Branches

| Branch | Responsibility |
|---|---|
| Governance | Legislative protocol, clerk flows, validation, votes, and approval state |
| Execution | Task routing, commitments, dispatch, and output validation |
| Adjudication | Guardian alerts, override/review logic, sanctions, settlement |
| Observatory | Aggregated reads, websocket event stream, dashboard, event bus |

## Core Runtime Files

| Path | Responsibility |
|---|---|
| `oasis/api.py` | FastAPI app, lifespan, router registration, health endpoint, websocket |
| `oasis/server.py` | Uvicorn entrypoint for local development |
| `oasis/governance/` | Governance branch implementation and endpoints |
| `oasis/execution/` | Execution branch implementation and endpoints |
| `oasis/adjudication/` | Adjudication branch implementation and endpoints |
| `oasis/observatory/` | Dashboard, event bus, websocket, REST summaries |
| `oasis/social_platform/` | Retained platform/channel/database primitives from the fork base |

## Key Design Constraints

- Agents are external clients. They do not run embedded inside the original OASIS runtime model.
- The platform exposes HTTP and websocket interfaces first; internal branch services sit behind that API surface.
- This repo is a hard fork and should not be treated as if upstream docs automatically describe current behavior.

## External Dependencies

| Integration | Usage |
|---|---|
| `mitosis-prototype` | Main runtime consumer through the HTTP platform adapter |
| `mitosis-control-plane` | Health checks, platform registry, observatory/operator access |
| `mitosis-cicd` | Conceptual CI contract only; workflow is inlined because the repo is public |
