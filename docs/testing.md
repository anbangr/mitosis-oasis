# Testing

## Main Test Command

```bash
pytest -v
```

## Test Coverage Shape

| Area | What the tests cover |
|---|---|
| FastAPI routes | API-level behavior, request validation, and response contracts |
| Branch logic | Governance, execution, adjudication rules and service behavior |
| Observatory | summary endpoints, leaderboard/timeseries aggregations, websocket behavior |
| E2E HTTP | full legislative pipeline via FastAPI `TestClient` |

## Pytest Notes

- `testpaths = ["test"]`
- legacy upstream infra and agent tests are excluded with `norecursedirs = ["test/infra", "test/agent"]`
- async tests run with `asyncio_mode = "auto"`

## Merge Expectations

- Run `pytest -v` for any behavior change.
- If a change affects the HTTP contract, update or add API-level tests instead of only relying on unit-level coverage.
- If a change affects observatory output or websocket behavior, add or update tests in `test/observatory/`.
