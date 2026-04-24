# Flow: Startup And Shutdown

## Sequence

```mermaid
sequenceDiagram
    participant Uvicorn as Uvicorn
    participant API as oasis.api lifespan
    participant Core as Platform + Channel
    participant Branches as branch DB init
    participant Obs as EventBus

    Uvicorn->>API: Start app
    API->>Core: Create Channel and Platform
    API->>Core: Start platform task
    API->>Branches: Init governance/execution/adjudication/observatory DBs
    API->>Obs: Init EventBus
    API-->>Uvicorn: App ready
    Uvicorn->>API: Shutdown
    API->>Core: Send EXIT action
    API->>Core: Await platform task or cancel
```

## Notes

- Health may be up only after both platform runtime and branch DB initialization complete.
- Shutdown tries graceful exit first, then falls back to task cancellation.
