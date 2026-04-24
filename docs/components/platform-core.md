# Platform Core

## Purpose

The platform core is the shared runtime that turns OASIS from a library-shaped simulation into a long-running HTTP service for external agents and experiment runners.

## Responsibilities

- create and own the FastAPI app lifecycle
- initialize Platform + Channel runtime state
- register branch routers and websocket endpoints
- provide core health and startup behavior

## Structure

| Path | Responsibility |
|---|---|
| `oasis/api.py` | main app, lifespan, health endpoint, router composition |
| `oasis/server.py` | uvicorn dev entrypoint |
| `oasis/social_platform/` | platform, channel, database, action dispatch primitives |

## Interfaces

- Input: HTTP requests, websocket subscriptions, internal action dispatches
- Output: HTTP responses, realtime events, platform state transitions

## Runtime Flow

1. Lifespan starts the `Platform` and its async task.
2. Branch databases and services are initialized.
3. Routers are attached for governance, execution, adjudication, and observatory.
4. Requests dispatch actions through the shared runtime.

## Failure Modes

- startup succeeds but branch DB init is incomplete
- platform task shutdown hangs
- route-level success masks deeper platform state issues

## Tests

- API health tests
- route tests across branch surfaces

## Change Risks

- changes here affect every branch and every external consumer
