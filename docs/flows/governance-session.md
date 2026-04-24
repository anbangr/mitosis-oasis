# Flow: Governance Session

## Sequence

```mermaid
sequenceDiagram
    participant Client as Prototype or external agent
    participant GovAPI as Governance API
    participant SM as State machine
    participant Clerks as Clerk layer
    participant Validators as DAG/Fairness/Constitution/Voting
    participant DB as Governance DB

    Client->>GovAPI: Start or progress session
    GovAPI->>SM: Validate current state transition
    SM->>Clerks: Route step to clerk logic
    Clerks->>Validators: Run deterministic checks
    Validators->>DB: Persist intermediate or final state
    DB-->>GovAPI: Session state
    GovAPI-->>Client: Next state / approval / failure
```

## Notes

- The exact route differs by message type, but the stable pattern is state transition -> clerk logic -> validators -> persisted session state.
- When behavior is wrong, inspect whether the bug is in state transition logic or a validator submodule.
