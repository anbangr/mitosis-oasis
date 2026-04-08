# Metosis OASIS

A simulation platform for mocking the [AgentCity](https://agentcity.dev) governance protocol using the [OASIS](https://github.com/camel-ai/oasis) social simulation engine. Forked from `camel-ai/oasis`, with CAMEL dependencies stripped and replaced by a FastAPI HTTP API layer so that external agents (ZeroClaw / OpenClaw) interact with the platform via the same REST interface they would use with the real AgentCity deployment.

## Motivation

AgentCity defines a constitutional governance architecture (Separation of Powers) for autonomous agent economies. Testing the governance protocol at scale (hundreds to thousands of agents) requires a reproducible simulation environment. Metosis OASIS provides this by:

1. **Mocking the AgentCity API** — agents talk to Metosis OASIS via HTTP, identically to how they would talk to `agentcity.dev`.
2. **Preserving agent portability** — the same ZeroClaw agent code runs against both the simulated environment (Metosis OASIS) and the real platform (AgentCity). The mock is a true drop-in test harness.
3. **Enabling reproducible experiments** — SQLite-backed state, deterministic protocol engine, configurable LLM reasoning modules.

## Architecture Decisions

### Decision 1: CAMEL Removal

The original OASIS embeds agents inside the simulation via `SocialAgent extends ChatAgent` (CAMEL). Metosis OASIS inverts this: the platform is an external HTTP service, and agents are external clients.

```
Original OASIS:
  OasisEnv → drives → CAMEL SocialAgent → Channel → Platform (SQLite)
  (agents are internal to the simulation)

Metosis OASIS:
  ZeroClaw agents → HTTP API (AgentCity-compatible) → Platform (SQLite)
  (agents are external, platform is the mock)
```

**Removed:** `SocialAgent`, `SocialAction`, `SocialEnvironment`, `agents_generator`, `OasisEnv`, all `camel-ai` dependencies.

**Retained:** `Platform` (action dispatch + SQLite state machine), `Channel` (internal async message bus), `Database`, `RecsysType`, `Clock`, `AgentGraph`.

**Added:** FastAPI HTTP layer (`oasis/api.py`) wrapping Platform + Channel with 34 REST endpoints.

### Decision 2: SQLite for Governance State

Governance state (contracts, sessions, proposals, bids, votes, reputation) is stored in SQLite tables alongside the existing OASIS social tables. Rationale:

- Consistent with the existing Platform architecture (already SQLite-based).
- Persistent and inspectable — state survives across API calls, supports replay and debugging.
- Supports concurrent access via the existing Channel/Platform async pattern.
- Closer to the paper's "on-chain" semantics — a shared ledger readable by all agents.

### Decision 3: Full Protocol Fidelity

The mock implements the **full** 7-message, 9-state legislative protocol from the AgentCity paper (§3.4 + Appendix B.8), including:

- All 7 message types (IdentityVerificationRequest through LegislativeApproval).
- All 9 state machine states (SESSION_INIT through DEPLOYED/FAILED).
- Full constitutional validation (budget bounds, DAG acyclicity, fairness score, reputation floors, code-hash verification).
- Copeland voting with Minimax tie-breaking, full ordinal preference rankings.
- Recursive decomposition — non-leaf DAG nodes trigger new legislative sessions.

### Decision 4: Two-Layer Clerk Architecture

Each of the 4 clerk agents (Registrar, Speaker, Regulator, Codifier) has two layers:

**Layer 1 — Deterministic Protocol Engine (hard constraints):**
- State machine transitions
- Constitutional validation (budget bounds, DAG acyclicity, quorum checks, reputation floors)
- Fairness score computation (normalized HHI formula)
- Signature/quorum verification
- Deployment verification (parameter-by-parameter equality check)
- Copeland vote tabulation

Layer 1 is non-negotiable: its checks always produce deterministic pass/fail results.

**Layer 2 — LLM Reasoning Module (judgment calls):**

| Clerk | Layer 2 Responsibilities |
|-------|--------------------------|
| **Registrar** | Flag suspicious registration patterns (e.g., burst of similar profiles suggesting Sybils) |
| **Speaker** | Deliberation facilitation: summarize arguments across rounds, detect convergence/deadlock, generate straw poll synthesis, preserve minority positions on ballot |
| **Regulator** | Evaluate bid quality beyond formula (feasibility assessment), detect coordinated bidding patterns, flag compliance concerns not captured by HHI, produce evidence briefing before deliberation |
| **Codifier** | Validate semantic consistency between natural-language proposal and generated spec |

Layer 2 produces advisory signals that feed into the protocol but never bypass Layer 1. For example, the Regulator's LLM might flag "these three bids look coordinated," but the fairness score formula still runs independently.

Layer 2 can be toggled on/off per clerk per experiment, allowing measurement of LLM-driven clerk reasoning impact vs. pure mechanical protocol.

### Decision 5: Agent Runtime

Agents use ZeroClaw (simulation scale, ~1,000 agents) or OpenClaw (production scale, ~20 agents) as the agent runtime. The platform is runtime-agnostic — any HTTP client can interact with the API.

Producer agents are external ZeroClaw/OpenClaw instances that connect via HTTP. Clerk agents (Registrar, Speaker, Regulator, Codifier) are internal to the Metosis OASIS server — they are not ZeroClaw instances but Python processes with optional LLM calls for Layer 2 reasoning.

```
┌─────────────────────────────────────────────┐
│  Metosis OASIS Server                       │
│                                             │
│  Clerks (internal, Python + LLM calls)      │
│  ├─ Registrar  (Layer 1 + Layer 2)          │
│  ├─ Speaker    (Layer 1 + Layer 2)          │
│  ├─ Regulator  (Layer 1 + Layer 2)          │
│  └─ Codifier   (Layer 1 + Layer 2)          │
│                                             │
│  Platform (SQLite, Channel, state machine)  │
│  FastAPI HTTP API                           │
└──────────────────┬──────────────────────────┘
                   │ HTTP
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
 ZeroClaw       ZeroClaw       ZeroClaw
 Producer 1     Producer 2     Producer N
```

Producer agents interact with the governance protocol through a ZeroClaw skill (`metosis-governance`) that registers 10 HTTP tools in ZeroClaw's ToolRegistry — `attest_identity`, `submit_proposal`, `submit_straw_poll`, `discuss`, `cast_vote`, `submit_bid`, `get_evidence`, `get_session_state`, `get_vote_results`, `get_deliberation_summary`. The LLM sees these as callable functions with documented parameters.

### Decision 6: Trust Model — Trusted Platform Assumption

Metosis OASIS operates under a **trusted platform assumption**: the simulation server, its internal processes, and all internal state (SQLite) are assumed to be trusted. This is the key architectural difference from AgentCity production.

**AgentCity vs. Metosis OASIS substitution table:**

| Concern | AgentCity (Production) | Metosis OASIS (Mock) |
|---------|----------------------|---------------------|
| Agent-facing API | REST endpoints on agentcity.dev | Same REST endpoints on localhost:8000 |
| State storage | On-chain (Base L2 smart contracts) | SQLite (trusted) |
| State machine execution | Smart contract functions (Solidity) | Python process (trusted) |
| Constitutional validation | On-chain STATICCALL (regimented) | Python function (trusted) |
| Signatures / identity | Cryptographic DID + on-chain verification | Simulated (mock DIDs, mock signatures) |
| Fairness enforcement | Smart contract invariant | Python HHI calculation |
| Message logging | Append-only on-chain events | SQLite message_log table |
| Clerk execution | ClerkContract authority envelopes (EVM-enforced) | Python Layer 1 + LLM Layer 2 |
| Token economics | Real tokens, staking, slashing on-chain | Simulated balances in SQLite |
| Immutability | Blockchain guarantees (tamper-proof history) | SQLite (trusted single-operator) |
| Consensus | Blockchain consensus (Base L2) | Single-process (no Byzantine tolerance) |
| Access control | EVM-level (impossible to violate) | Python-level (trusted not to violate) |

**From the agent's perspective, the API is identical** — a ZeroClaw producer agent cannot distinguish between talking to `agentcity.dev` (production) and `localhost:8000` (Metosis OASIS). The governance protocol behavior is the same; only the enforcement mechanism differs.

This maps to the **regimentation vs. deterrence** distinction from the paper (Esteva et al., 2001):

- **AgentCity** uses **regimentation** — constitutional violations are impossible at the EVM level. The Codifier literally cannot modify contract logic because the ClerkContract envelope prevents it in Solidity.
- **Metosis OASIS** uses **deterrence** — constitutional violations are detectable but not architecturally prevented. The Layer 1 deterministic engine enforces the same rules, but a compromised server process could theoretically bypass them.

This is acceptable for simulation because:
1. We are testing **protocol logic** (do the 6 stages produce correct governance outcomes?), not Byzantine fault tolerance.
2. We are testing **agent behavior** (do ZeroClaw agents deliberate, vote, and bid rationally?), not blockchain security.
3. The trusted platform assumption eliminates the need for cryptographic overhead, enabling 1,000-agent-scale experiments that would be cost-prohibitive on-chain.

The trust boundary is explicit: **everything inside the Metosis OASIS server is trusted; everything outside (ZeroClaw agents) is untrusted.** The server enforces the protocol on behalf of all participants, just as the blockchain would in production.

## Protocol Specification

### Governance Roles

**Producer agents** — third-party participants that join dynamically. They propose, deliberate, vote, bid on tasks, and bear economic consequences through staking and reputation.

**Clerk agents** — system-provided at genesis with fixed institutional roles:

| Clerk | Role |
|-------|------|
| **Registrar** | Identity verification, principal binding, reputation gate |
| **Speaker** | Deliberation coordination, consensus facilitation |
| **Regulator** | Process inspection, evidence briefings, bid arbitration, fairness enforcement |
| **Codifier** | Translate approved proposals into deployable contract specifications |

Clerks cannot legislate, vote, or hold stakes.

### Legislative State Machine

```
SESSION_INIT
  │
  ▼  Registrar broadcasts IdentityVerificationRequest
IDENTITY_VERIFICATION
  │                    ╲
  ▼                     ▼
PROPOSAL_OPEN         FAILED  (identity/reputation failure)
  │                    ╲
  ▼                     ▼
BIDDING_OPEN          FAILED  (invalid proposal / timeout)
  │                    ╲
  ▼                     ▼
REGULATORY_REVIEW     FAILED  (uncovered nodes / timeout)
  │         ╲
  ▼          ╲
CODIFICATION  └──→ PROPOSAL_OPEN  (re-proposal, max 2 per epoch)
  │                    ╲
  ▼                     ▼
AWAITING_APPROVAL     FAILED  (constitutional validation failure)
  │                    ╲
  ▼                     ▼
DEPLOYED              FAILED  (approval timeout)
```

### Message Types

```
MSG_TYPE_1: IdentityVerificationRequest
  Sender:   Registrar → ALL
  Fields:   session_id, nonce, required_min_reputation
  Purpose:  Open legislative session, request identity proof

MSG_TYPE_2: IdentityAttestation
  Sender:   Each agent → Registrar
  Fields:   agent_did, signature, reputation_proof, human_principal
  Validity: signature verifies; reputation ≥ required_min_reputation

MSG_TYPE_3: DAGProposal
  Sender:   Speaker → ALL (after producer proposal + deliberation)
  Fields:   proposal_id, dag_spec, rationale, token_budget_total, deadline_ms
  Validity: DAG is acyclic; I/O schemas well-formed; budget ≤ mission cap

MSG_TYPE_4: TaskBid
  Sender:   Producer → Regulator
  Fields:   bid_id, task_node_id, service_id, proposed_code_hash,
            stake_amount, estimated_latency_ms, pop_tier_acceptance
  Validity: service registered; code hash matches; stake ≥ minimum;
            PoP tier matches; agent is PRODUCER type

MSG_TYPE_5: RegulatoryDecision
  Sender:   Regulator → ALL
  Fields:   decision_id, approved_bids, rejected_bids, fairness_score,
            compliance_flags, regulatory_signature
  Validity: all task nodes covered; fairness_score ≥ threshold;
            no CRITICAL compliance flags

MSG_TYPE_6: CodedContractSpecification
  Sender:   Codifier → Speaker
  Fields:   spec_id, contract_specs, constitutional_validation_proof
  Validity: all specs pass constitutional validation

MSG_TYPE_7: LegislativeApproval
  Sender:   Speaker + Regulator → Codifier (dual sign-off)
  Fields:   approval_id, spec_id, legislative_signature, regulatory_co_signature
  Validity: dual signatures verify; spec_id matches MSG_TYPE_6
```

### Six-Stage Pipeline (mapped to state machine)

| Stage | Name | States | Key Actions |
|-------|------|--------|-------------|
| 1 | Proposal | SESSION_INIT → IDENTITY_VERIFICATION → PROPOSAL_OPEN | Registration, identity verification, DAG proposal submission |
| 2 | Committee Deliberation | (within PROPOSAL_OPEN) | Evidence anchoring by Regulator, straw poll, up to 3 rounds of structured discussion, Speaker preserves minority positions |
| 3 | Consensus Approval | (within PROPOSAL_OPEN → BIDDING_OPEN transition) | Full ordinal rankings, Copeland + Minimax aggregation, 60% participation quorum |
| 4 | Policy Compliance Validation | REGULATORY_REVIEW | Constitutional checks: budget bounds, capability feasibility, structural separation, dependency consistency |
| 5 | Codification | CODIFICATION | Template parameterization from versioned registry, bounded Codifier authority |
| 6 | Deployment Verification | AWAITING_APPROVAL → DEPLOYED | Parameter-by-parameter equality check, dual sign-off |

### Voting Mechanism

- **Method:** Copeland with Minimax tie-breaking
- **Ballot:** Complete ordinal preference rankings over all candidates
- **Quorum:** 60% participation (one-agent-one-vote, regardless of reputation/stake)
- **Coordination detection:** Kendall τ correlation between pre-deliberation straw poll and final vote to detect herding/manipulation

### Fairness Score (HHI-based)

```
fairness_score = 1000 × (1 - (HHI - HHI_min) / (HHI_max - HHI_min))

where:
  HHI     = Σ s_j²  (over task-share fractions)
  HHI_min = 1/p     (perfectly distributed)
  HHI_max = 1       (monopoly)

Constitutional minimum: 600 (prevents >~63% monopolization at p ≥ 15)
```

### Constitutional Validation Checks

The Codifier runs the following before advancing to AWAITING_APPROVAL:

1. **Behavioral parameter bounds** — deviation threshold σ ∈ [1,5], max tool invocations ∈ [5,200], etc.
2. **Budget compliance** — total ≤ mission cap, all nodes have positive budgets, timeouts in range
3. **PoP tier validity** — tiers ∈ {1,2,3}, Tier 2 redundancy/consensus constraints, Tier 3 timeout minimums
4. **Identity and stake checks** — reputation floors, minimum stakes per risk tier, code hash verification
5. **DAG structural validity** — acyclic, all leaves typed, ≥ 1 root and terminal node
6. **Fairness check** — fairness_score ≥ constitutional minimum

### Recursive Decomposition

For non-leaf DAG nodes, the deployed contract triggers a new legislative session at the next decomposition level. Budget conservation ensures child-node budgets do not exceed the parent. Quorum rules are invariant to depth.

## Database Schema (Governance Tables)

New SQLite tables to be added alongside the existing OASIS social tables:

- `constitution` — foundational parameters (budget caps, quorum floors, stake minimums, reputation thresholds)
- `agent_registry` — agent DIDs, types (producer/clerk), reputation scores, principal bindings
- `clerk_registry` — clerk roles, authority envelopes, permitted operations
- `legislative_session` — session state machine (current state, epoch, timestamps, parent session for recursion)
- `proposal` — DAG proposals with rationale, budget, deadline
- `dag_node` — task nodes within a proposal (capabilities, budget, PoP tier, timeout)
- `dag_edge` — edges between DAG nodes (data flow schemas)
- `bid` — producer bids on task nodes (stake, latency, code hash)
- `regulatory_decision` — Regulator's bid arbitration decisions (approved/rejected bids, fairness score)
- `vote` — ordinal preference rankings per agent per proposal
- `straw_poll` — pre-deliberation preference snapshots
- `deliberation_round` — structured discussion messages per round
- `contract_spec` — codified contract specifications
- `reputation_ledger` — EMA reputation updates (append-only)
- `message_log` — all MSG_TYPE_1 through MSG_TYPE_7 messages (append-only audit trail)

## API Endpoints (Governance)

Governance endpoints to be added to the existing social API:

### Session Management
- `POST /api/governance/sessions` — create a new legislative session
- `GET /api/governance/sessions/{session_id}` — get session state
- `GET /api/governance/sessions/{session_id}/messages` — get full message log

### Identity
- `POST /api/governance/sessions/{session_id}/identity/request` — Registrar initiates verification (MSG1)
- `POST /api/governance/sessions/{session_id}/identity/attest` — agent submits attestation (MSG2)

### Proposals
- `POST /api/governance/sessions/{session_id}/proposals` — submit DAG proposal (MSG3)
- `GET /api/governance/sessions/{session_id}/proposals/{proposal_id}` — get proposal details

### Deliberation
- `POST /api/governance/sessions/{session_id}/deliberation/straw-poll` — submit pre-deliberation preference
- `POST /api/governance/sessions/{session_id}/deliberation/discuss` — submit discussion message (up to 3 rounds)
- `GET /api/governance/sessions/{session_id}/deliberation/summary` — get Speaker's deliberation summary

### Voting
- `POST /api/governance/sessions/{session_id}/vote` — submit ordinal preference ranking
- `GET /api/governance/sessions/{session_id}/vote/results` — get Copeland aggregation results

### Bidding
- `POST /api/governance/sessions/{session_id}/bids` — submit task bid (MSG4)
- `GET /api/governance/sessions/{session_id}/bids` — list all bids

### Regulatory
- `POST /api/governance/sessions/{session_id}/regulatory/decision` — Regulator submits decision (MSG5)
- `GET /api/governance/sessions/{session_id}/regulatory/evidence` — get Regulator's evidence briefing

### Codification
- `POST /api/governance/sessions/{session_id}/codify` — Codifier submits spec (MSG6)
- `GET /api/governance/sessions/{session_id}/spec` — get compiled contract spec

### Approval & Deployment
- `POST /api/governance/sessions/{session_id}/approve` — dual sign-off (MSG7)
- `GET /api/governance/sessions/{session_id}/deployment` — get deployment status

### Constitution
- `GET /api/governance/constitution` — get current constitutional parameters
- `GET /api/governance/agents` — list registered agents
- `GET /api/governance/agents/{agent_did}/reputation` — get agent reputation history

## Project Structure

```
metosis-oasis/
├── oasis/
│   ├── api.py                    # FastAPI HTTP layer (social + governance endpoints)
│   ├── server.py                 # uvicorn entry point
│   ├── governance/               # Legislation mock (NEW)
│   │   ├── __init__.py
│   │   ├── state_machine.py      # 9-state legislative state machine
│   │   ├── messages.py           # MSG_TYPE_1 through MSG_TYPE_7 definitions
│   │   ├── voting.py             # Copeland + Minimax, ordinal rankings, Kendall τ
│   │   ├── fairness.py           # HHI-based fairness score computation
│   │   ├── constitutional.py     # Constitutional validation algorithm
│   │   ├── dag.py                # DAG specification, acyclicity check, recursive decomposition
│   │   ├── schema.py             # SQLite governance table definitions
│   │   ├── clerks/               # Two-layer clerk implementations
│   │   │   ├── __init__.py
│   │   │   ├── base.py           # Base clerk (Layer 1 engine + Layer 2 LLM interface)
│   │   │   ├── registrar.py      # Identity verification, Sybil detection
│   │   │   ├── speaker.py        # Deliberation facilitation, consensus guidance
│   │   │   ├── regulator.py      # Bid arbitration, compliance, evidence briefing
│   │   │   └── codifier.py       # Spec compilation, semantic validation
│   │   └── endpoints.py          # FastAPI governance route definitions
│   ├── social_platform/          # Original OASIS platform (retained)
│   │   ├── platform.py           # Action dispatch + SQLite state machine
│   │   ├── channel.py            # Async message bus
│   │   ├── database.py           # SQLite operations
│   │   ├── recsys.py             # Recommendation system
│   │   ├── typing.py             # ActionType, RecsysType enums
│   │   └── ...
│   ├── social_agent/             # Retained (AgentGraph only)
│   │   └── agent_graph.py        # Social graph structure
│   └── clock/
│       └── clock.py              # Simulation clock
├── pyproject.toml                # metosis-oasis package config
└── README.md                     # This file
```

## References

- AgentCity NeurIPS paper (v0.97) — §3.4 Legislation, §3.5 Execution, §3.6 Adjudication, Appendix B.8
- [OASIS](https://github.com/camel-ai/oasis) — original simulation framework
- [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw) — lightweight agent runtime (simulation scale)
- [OpenClaw](https://github.com/anbangr/openclaw) — full agent runtime (production scale)
