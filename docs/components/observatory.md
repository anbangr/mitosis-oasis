# Observatory

## Purpose

The observatory component is the visibility layer for OASIS. It exposes summaries, timeseries, dashboards, and realtime events for operators and other services.

## Responsibilities

- event bus management
- websocket streaming
- summary/leaderboard/timeseries REST outputs
- operator dashboard support

## Structure

| Path | Responsibility |
|---|---|
| `oasis/observatory/endpoints.py` | REST endpoints |
| `oasis/observatory/event_bus.py` | event fanout and replay support |
| `oasis/observatory/websocket.py` | websocket event handling |
| `oasis/observatory/dashboard.py` | dashboard routes |

## Interfaces

- Input: events and state from governance, execution, and adjudication
- Output: dashboards, REST summaries, websocket streams

## Runtime Flow

1. Branches emit events or update observatory state.
2. Event bus stores or distributes the updates.
3. REST and websocket consumers read the normalized view.

## Failure Modes

- event bus not initialized
- websocket endpoint available but no useful event data
- summary endpoints lagging behind branch state changes

## Tests

- summary, leaderboard, timeseries, and websocket tests under `test/observatory/`

## Change Risks

- observability outputs are effectively contracts for both humans and downstream services
