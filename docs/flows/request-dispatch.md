# Flow: Request Dispatch

## Sequence

```mermaid
sequenceDiagram
    participant Client as External client
    participant Route as FastAPI route
    participant Dispatch as _dispatch()
    participant Channel as Channel
    participant Platform as Platform task

    Client->>Route: HTTP request
    Route->>Dispatch: Build action request
    Dispatch->>Channel: write_to_receive_queue(...)
    Platform->>Channel: read action
    Platform->>Platform: Execute action
    Platform->>Channel: write result
    Dispatch->>Channel: read_from_send_queue(...)
    Dispatch-->>Route: result
    Route-->>Client: HTTP response
```

## Notes

- This is the core request path for platform-backed actions.
- If `_dispatch()` fails, the failure may be in route validation, channel state, or platform logic rather than FastAPI itself.
