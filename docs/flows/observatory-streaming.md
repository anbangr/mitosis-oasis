# Flow: Observatory Streaming

## Sequence

```mermaid
sequenceDiagram
    participant Branch as Gov/Exec/Adj branch
    participant Bus as EventBus
    participant REST as Observatory REST
    participant WS as WebSocket
    participant Client as Operator or consumer

    Branch->>Bus: Emit event
    Bus-->>REST: Persist/aggregate signal
    Bus-->>WS: Push event stream
    Client->>REST: Read summary/leaderboard/timeseries
    REST-->>Client: Aggregated view
    WS-->>Client: Live event updates
```

## Notes

- REST and websocket consumers share the same underlying observability surface.
- Event bus initialization issues can break both live streams and summary freshness.
