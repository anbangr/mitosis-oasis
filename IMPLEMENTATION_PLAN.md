# Metosis OASIS — Implementation Plan

## Phase Overview

| Phase | Name | Modules | Tests | Est. Lines |
|-------|------|---------|-------|------------|
| P0 | Test Infrastructure & Cleanup | conftest, fixtures, existing test triage | ~15 tests | ~300 |
| P1 | Governance Schema | `governance/schema.py` | ~25 tests | ~400 |
| P2 | State Machine | `governance/state_machine.py` | ~35 tests | ~500 |
| P3 | Voting & Fairness | `governance/voting.py`, `governance/fairness.py` | ~40 tests | ~600 |
| P4 | DAG & Constitutional Validation | `governance/dag.py`, `governance/constitutional.py` | ~30 tests | ~500 |
| P5 | Messages | `governance/messages.py` | ~20 tests | ~300 |
| P6 | Clerks (Layer 1 — Deterministic) | `governance/clerks/*.py` | ~45 tests | ~800 |
| P7 | Clerks (Layer 2 — LLM Reasoning) | `governance/clerks/*.py` (LLM module) | ~25 tests | ~500 |
| P8 | Governance API Endpoints | `governance/endpoints.py`, updated `api.py` | ~40 tests | ~600 |
| P9 | Recursive Decomposition | `governance/dag.py` extension | ~15 tests | ~300 |
| P10 | Integration & E2E | Full pipeline tests | ~20 tests | ~400 |
| P11 | ZeroClaw Governance Skill | `skills/metosis-governance/SKILL.toml` | ~10 tests | ~200 |
| P12 | Execution: Schema, Routing & Commitment | `execution/schema.py`, `router.py`, `commitment.py`, `config.py` | ~25 tests | ~450 |
| P13 | Execution: Runner, Validator & Endpoints | `execution/runner.py`, `validator.py`, `synthetic.py`, `endpoints.py` | ~35 tests | ~650 |
| P14 | Adjudication: Guardian, Sanctions & Settlement | `adjudication/guardian.py`, `sanctions.py`, `settlement.py`, `treasury.py` | ~35 tests | ~600 |
| P15 | Adjudication: Override Panel, Endpoints & LLM | `adjudication/override_panel.py`, `coordination.py`, `endpoints.py` | ~25 tests | ~450 |
| P16 | ZeroClaw Execution Skill + Cross-Branch E2E | Skill update (5 execution tools) + 3-branch E2E tests | ~12 tests | ~350 |
| P17 | Observatory: Event Bus, WebSocket & Dashboard | `observatory/event_bus.py`, `websocket.py`, `dashboard.py`, `endpoints.py` | ~20 tests | ~800 |
| **Total** | | | **~472 tests** | **~9,100** |

---

## P0: Test Infrastructure & Cleanup

**Goal:** Establish a clean test foundation before writing new code.

### Tasks
- [ ] P0.1 — Triage existing tests: identify which `test/infra/database/` tests still pass after CAMEL removal
- [ ] P0.2 — Remove broken `test/agent/` tests (all depend on deleted SocialAgent/SocialAction)
- [ ] P0.3 — Create `test/governance/` directory structure mirroring `oasis/governance/`
- [ ] P0.4 — Create `test/governance/conftest.py` with shared fixtures:
  - `db_path` — temp SQLite database per test (auto-cleanup)
  - `governance_db` — initialized governance schema
  - `sample_agents` — 5 pre-registered producer agents + 4 clerks
  - `sample_constitution` — default constitutional parameters
  - `sample_dag` — a simple 3-node DAG for reuse
- [ ] P0.5 — Create `test/api/conftest.py` with FastAPI `TestClient` fixture
- [ ] P0.6 — Verify existing infra/database tests pass with `pytest test/infra/`

### Test Matrix (P0)
| Test | What it validates |
|------|-------------------|
| `test_existing_infra_pass` | All retained `test/infra/database/` tests pass |
| `test_governance_fixtures` | Fixtures create valid DB, agents, constitution |
| `test_api_client_health` | TestClient can hit `/api/health` |

---

## P1: Governance Schema

**Goal:** Define all 15 governance SQLite tables.

### Module: `oasis/governance/schema.py`
- [ ] P1.1 — `create_governance_tables(db_path)` — DDL for all tables
- [ ] P1.2 — Tables:
  - `constitution` — (param_name TEXT PK, param_value REAL, param_type TEXT, description TEXT, updated_at TIMESTAMP)
  - `agent_registry` — (agent_did TEXT PK, agent_type TEXT CHECK(producer/clerk), display_name TEXT, human_principal TEXT, reputation_score REAL DEFAULT 0.5, registered_at TIMESTAMP, active BOOLEAN DEFAULT 1)
  - `clerk_registry` — (agent_did TEXT PK, clerk_role TEXT CHECK(registrar/speaker/regulator/codifier), authority_envelope JSON, FK agent_registry)
  - `legislative_session` — (session_id TEXT PK, state TEXT, epoch INTEGER, parent_session_id TEXT NULL FK self, parent_node_id TEXT NULL, mission_budget_cap REAL, created_at TIMESTAMP, updated_at TIMESTAMP, failed_reason TEXT NULL)
  - `proposal` — (proposal_id TEXT PK, session_id TEXT FK, proposer_did TEXT FK, dag_spec JSON, rationale TEXT, token_budget_total REAL, deadline_ms INTEGER, status TEXT, created_at TIMESTAMP)
  - `dag_node` — (node_id TEXT PK, proposal_id TEXT FK, label TEXT, service_id TEXT, input_schema JSON, output_schema JSON, pop_tier INTEGER CHECK(1-3), redundancy_factor INTEGER DEFAULT 1, consensus_threshold INTEGER DEFAULT 1, token_budget REAL, timeout_ms INTEGER, risk_tier TEXT)
  - `dag_edge` — (edge_id INTEGER PK AUTOINCREMENT, proposal_id TEXT FK, from_node_id TEXT FK, to_node_id TEXT FK, data_flow_schema JSON)
  - `bid` — (bid_id TEXT PK, session_id TEXT FK, task_node_id TEXT FK, bidder_did TEXT FK, service_id TEXT, proposed_code_hash TEXT, stake_amount REAL, estimated_latency_ms INTEGER, pop_tier_acceptance INTEGER, status TEXT DEFAULT 'pending', created_at TIMESTAMP)
  - `regulatory_decision` — (decision_id TEXT PK, session_id TEXT FK, approved_bids JSON, rejected_bids JSON, fairness_score REAL, compliance_flags JSON, regulatory_signature TEXT, created_at TIMESTAMP)
  - `straw_poll` — (poll_id INTEGER PK AUTOINCREMENT, session_id TEXT FK, agent_did TEXT FK, proposal_id TEXT FK, preference_ranking JSON, created_at TIMESTAMP)
  - `deliberation_round` — (round_id INTEGER PK AUTOINCREMENT, session_id TEXT FK, round_number INTEGER CHECK(1-3), agent_did TEXT FK, message TEXT, created_at TIMESTAMP)
  - `vote` — (vote_id INTEGER PK AUTOINCREMENT, session_id TEXT FK, agent_did TEXT FK, preference_ranking JSON, created_at TIMESTAMP)
  - `contract_spec` — (spec_id TEXT PK, session_id TEXT FK, collaboration_contract_spec JSON, guardian_module_spec JSON, verification_module_spec JSON, gate_module_spec JSON, service_contract_specs JSON, validation_proof TEXT, status TEXT, created_at TIMESTAMP)
  - `reputation_ledger` — (entry_id INTEGER PK AUTOINCREMENT, agent_did TEXT FK, old_score REAL, new_score REAL, performance_score REAL, lambda REAL, reason TEXT, created_at TIMESTAMP)
  - `message_log` — (log_id INTEGER PK AUTOINCREMENT, session_id TEXT FK, msg_type TEXT, sender_did TEXT, receiver TEXT, payload JSON, created_at TIMESTAMP)
- [ ] P1.3 — `seed_constitution(db_path)` — insert default constitutional parameters from the paper
- [ ] P1.4 — `seed_clerks(db_path)` — register the 4 clerk agents with authority envelopes

### Test Matrix (P1)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_schema_creation.py` | 3 | Tables created, idempotent re-creation, FK constraints enforced |
| `test_schema_constitution.py` | 5 | Default params seeded, all params present, value ranges correct, param update works, unknown param rejected |
| `test_schema_agent_registry.py` | 6 | Register producer, register clerk, duplicate DID rejected, type constraint enforced, reputation default 0.5, deactivation works |
| `test_schema_clerk_registry.py` | 4 | All 4 clerks registered, role constraint enforced, authority envelope stored, non-clerk DID rejected |
| `test_schema_session.py` | 4 | Session created with initial state, parent FK for recursive sessions, state update works, failed_reason stored |
| `test_schema_message_log.py` | 3 | Message logged, msg_type validated, chronological ordering |

**Total: ~25 tests**

---

## P2: State Machine

**Goal:** Implement the 9-state legislative state machine with all transitions and guards.

### Module: `oasis/governance/state_machine.py`
- [ ] P2.1 — `LegislativeState` enum: SESSION_INIT, IDENTITY_VERIFICATION, PROPOSAL_OPEN, BIDDING_OPEN, REGULATORY_REVIEW, CODIFICATION, AWAITING_APPROVAL, DEPLOYED, FAILED
- [ ] P2.2 — `LegislativeStateMachine` class:
  - `__init__(session_id, db_path)` — loads or creates session
  - `current_state` property
  - `transition(target_state, **context)` — validates guard conditions, updates DB, returns success/failure
  - `can_transition(target_state)` — check without executing
  - `history()` — returns ordered list of (state, timestamp, context) tuples from message_log
- [ ] P2.3 — Transition guards (each returns bool + reason):
  - `SESSION_INIT → IDENTITY_VERIFICATION`: Registrar broadcasts MSG1
  - `IDENTITY_VERIFICATION → PROPOSAL_OPEN`: all agents submitted valid MSG2, quorum met
  - `IDENTITY_VERIFICATION → FAILED`: identity/reputation failure
  - `PROPOSAL_OPEN → BIDDING_OPEN`: valid MSG3 received before timeout
  - `PROPOSAL_OPEN → FAILED`: timeout or invalid proposal
  - `BIDDING_OPEN → REGULATORY_REVIEW`: all task nodes have ≥1 valid bid, window expired
  - `BIDDING_OPEN → FAILED`: uncovered nodes at timeout
  - `REGULATORY_REVIEW → CODIFICATION`: valid MSG5, no CRITICAL flags
  - `REGULATORY_REVIEW → PROPOSAL_OPEN`: re-proposal requested (max 2 per epoch)
  - `CODIFICATION → AWAITING_APPROVAL`: valid MSG6 passes constitutional validation
  - `CODIFICATION → FAILED`: validation fails after max retries (default 2)
  - `AWAITING_APPROVAL → DEPLOYED`: MSG7 with dual signatures
  - `AWAITING_APPROVAL → FAILED`: approval timeout
- [ ] P2.4 — `TimeoutManager` — configurable timeouts per state (legislative_proposal_timeout, bidding_window, approval_timeout)
- [ ] P2.5 — Re-proposal counter (max 2 per epoch) tracked in session metadata

### Test Matrix (P2)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_state_enum.py` | 2 | All 9 states defined, FAILED is terminal |
| `test_happy_path.py` | 1 | Full SESSION_INIT → DEPLOYED traversal |
| `test_transitions_valid.py` | 13 | Each valid transition works with correct guards |
| `test_transitions_invalid.py` | 8 | Invalid transitions rejected (e.g., SESSION_INIT → DEPLOYED) |
| `test_guard_identity.py` | 4 | Quorum check, reputation floor, missing agents, partial attestation |
| `test_guard_proposal.py` | 3 | Valid DAG accepted, cyclic DAG rejected, budget exceeded rejected |
| `test_guard_bidding.py` | 3 | All nodes covered, uncovered nodes fail, window expiry |
| `test_guard_regulatory.py` | 3 | Valid decision advances, CRITICAL flag blocks, re-proposal counter |
| `test_guard_codification.py` | 3 | Constitutional pass advances, fail retries, max retry exceeded |
| `test_guard_approval.py` | 2 | Dual signature accepted, single signature rejected |
| `test_timeout.py` | 3 | Configurable timeouts, expiry triggers FAILED, timeout override |
| `test_reproposal.py` | 3 | Re-proposal increments counter, max 2 enforced, counter resets on new epoch |
| `test_history.py` | 2 | Transitions logged, chronological order |

**Total: ~35 tests** (some files test multiple scenarios)

---

## P3: Voting & Fairness

**Goal:** Implement Copeland voting with Minimax tie-breaking, ordinal rankings, Kendall τ, and HHI fairness.

### Module: `oasis/governance/voting.py`
- [ ] P3.1 — `CopelandVoting` class:
  - `add_ballot(agent_did, ranking: List[str])` — validates complete ordinal ranking
  - `compute_pairwise_matrix()` — NxN matrix of head-to-head wins
  - `copeland_scores()` — net wins per candidate
  - `minimax_tiebreak(tied_candidates)` — worst pairwise defeat as tiebreaker
  - `result()` → `VotingResult(winner, scores, pairwise_matrix, tiebreak_used)`
  - `quorum_met(total_eligible, threshold=0.6)` — participation check
- [ ] P3.2 — `kendall_tau(ranking_a, ranking_b)` — Kendall τ correlation coefficient
- [ ] P3.3 — `coordination_detection(straw_poll_rankings, final_rankings, threshold)` — compare pre/post deliberation rankings to detect herding
- [ ] P3.4 — `validate_ballot(ranking, candidates)` — ensure complete ranking, no duplicates, all candidates present

### Module: `oasis/governance/fairness.py`
- [ ] P3.5 — `hhi(shares: List[float])` → float — raw HHI
- [ ] P3.6 — `normalized_fairness_score(shares, num_producers)` → int (0-1000)
- [ ] P3.7 — `monopolization_bound(num_producers, min_fairness=600)` → float — max share any producer can hold
- [ ] P3.8 — `check_fairness(bid_assignments, min_score=600)` → `FairnessResult(score, passed, max_share, violator)`

### Test Matrix (P3)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_copeland_basic.py` | 5 | 3-candidate clear winner, Condorcet winner found, all-tied scenario, single candidate, 2-candidate |
| `test_copeland_minimax.py` | 4 | Tie broken by minimax, multiple ties, minimax with equal worst defeats, Condorcet cycle |
| `test_copeland_edge_cases.py` | 3 | Empty ballots, single voter, all identical rankings |
| `test_ballot_validation.py` | 5 | Complete ranking accepted, incomplete rejected, duplicates rejected, unknown candidate rejected, empty ranking rejected |
| `test_quorum.py` | 4 | 60% met, 59% fails, exactly 60%, all vote |
| `test_kendall_tau.py` | 5 | Identical rankings (τ=1), reversed rankings (τ=-1), partial agreement, single element, known hand-computed value |
| `test_coordination_detection.py` | 4 | No coordination detected (normal variance), suspicious convergence flagged, all identical pre/post (maximum herding), threshold sensitivity |
| `test_hhi.py` | 4 | Perfect distribution (1/p), monopoly (1.0), known 2-producer split, known 5-producer asymmetric |
| `test_fairness_score.py` | 4 | Score 1000 for equal dist, score 0 for monopoly, constitutional minimum 600 check, boundary at ~63% for p≥15 |
| `test_monopolization_bound.py` | 3 | p=2 bound ≈0.816, p=5 bound ≈0.72, p=15 bound ≈0.63 |
| `test_check_fairness.py` | 3 | Passing distribution, failing distribution with violator identified, edge case at boundary |

**Total: ~40 tests** (some aggregate multiple assertions)

---

## P4: DAG & Constitutional Validation

**Goal:** DAG specification, acyclicity verification, and the full constitutional validation algorithm.

### Module: `oasis/governance/dag.py`
- [ ] P4.1 — `DAGSpec` dataclass: nodes (List[DAGNode]), edges (List[DAGEdge])
- [ ] P4.2 — `DAGNode` dataclass: node_id, label, service_id, input_schema, output_schema, pop_tier, redundancy_factor, consensus_threshold, token_budget, timeout_ms, risk_tier
- [ ] P4.3 — `DAGEdge` dataclass: from_node_id, to_node_id, data_flow_schema
- [ ] P4.4 — `validate_dag(dag: DAGSpec)` → `DAGValidationResult`:
  - Acyclicity (topological sort)
  - All leaf nodes have PoP tier
  - ≥ 1 root node and ≥ 1 terminal node
  - No orphan nodes
  - Budget conservation (child sum ≤ parent)
  - I/O schema compatibility on edges
- [ ] P4.5 — `topological_sort(dag)` → ordered list or CycleError
- [ ] P4.6 — `find_roots(dag)` / `find_leaves(dag)` — helper functions

### Module: `oasis/governance/constitutional.py`
- [ ] P4.7 — `ConstitutionalValidator` class:
  - `__init__(db_path)` — loads current constitution params
  - `validate(spec: CodedContractSpec)` → `ValidationResult(passed, errors: List[ValidationError])`
- [ ] P4.8 — Six validation checks (each returns List[ValidationError]):
  - `_check_behavioral_params(spec)` — deviation σ ∈ [1,5], max tools ∈ [5,200], max msgs ∈ [10,500], escalation freeze ∈ [2,10]
  - `_check_budget_compliance(spec)` — total ≤ cap, all nodes positive, timeouts in range
  - `_check_pop_tier(spec)` — tiers ∈ {1,2,3}, Tier 2 redundancy/consensus, Tier 3 timeout minimum
  - `_check_identity_stake(spec, db_path)` — reputation floors, stake minimums, code hash verification
  - `_check_dag_structure(spec)` — delegates to `validate_dag()`
  - `_check_fairness(spec)` — delegates to `check_fairness()`

### Test Matrix (P4)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_dag_valid.py` | 4 | Linear chain (A→B→C), diamond (A→B,C→D), single node, complex 6-node DAG |
| `test_dag_invalid.py` | 5 | Cycle detected, no root, no terminal, orphan node, empty DAG |
| `test_dag_budget.py` | 3 | Budget conservation passes, child exceeds parent fails, zero budget fails |
| `test_dag_topo_sort.py` | 3 | Correct ordering, diamond ordering, cycle raises error |
| `test_constitutional_behavioral.py` | 4 | All params in range, σ out of range, tools out of range, multiple violations |
| `test_constitutional_budget.py` | 3 | Valid budget, exceeds cap, negative node budget |
| `test_constitutional_pop.py` | 4 | Tier 1 valid, Tier 2 redundancy check, Tier 2 consensus majority, Tier 3 timeout minimum |
| `test_constitutional_identity.py` | 3 | All agents meet floor, one below floor, unregistered agent |
| `test_constitutional_full.py` | 3 | Full validation passes, multiple failures aggregated, partial failures reported |

**Total: ~30 tests** (some combine multiple checks)

---

## P5: Messages

**Goal:** Define MSG_TYPE_1 through MSG_TYPE_7 with validation and serialization.

### Module: `oasis/governance/messages.py`
- [ ] P5.1 — `MessageType` enum: IDENTITY_VERIFICATION_REQUEST, IDENTITY_ATTESTATION, DAG_PROPOSAL, TASK_BID, REGULATORY_DECISION, CODED_CONTRACT_SPEC, LEGISLATIVE_APPROVAL
- [ ] P5.2 — Pydantic models for each message type (fields from paper spec)
- [ ] P5.3 — `validate_message(msg)` — type-specific validation (signature, required fields, FK existence)
- [ ] P5.4 — `log_message(db_path, session_id, msg)` — append to message_log table
- [ ] P5.5 — `get_session_messages(db_path, session_id, msg_type=None)` — query message log

### Test Matrix (P5)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_message_types.py` | 7 | Each MSG_TYPE creates valid model instance |
| `test_message_validation.py` | 7 | Each MSG_TYPE rejects invalid fields (missing required, wrong types) |
| `test_message_logging.py` | 3 | Messages logged to DB, filterable by type, chronological order |
| `test_message_serialization.py` | 3 | JSON round-trip, payload integrity, timestamp preservation |

**Total: ~20 tests**

---

## P6: Clerks — Layer 1 (Deterministic Protocol Engine)

**Goal:** Implement the deterministic logic for all 4 clerks.

### Module: `oasis/governance/clerks/base.py`
- [ ] P6.1 — `BaseClerk` abstract class:
  - `__init__(db_path, clerk_did, llm_enabled=False)`
  - `layer1_process(msg)` → deterministic result
  - `layer2_reason(context)` → LLM advisory (optional, P7)
  - `authority_check(action)` → bool (within authority envelope)

### Module: `oasis/governance/clerks/registrar.py`
- [ ] P6.2 — `Registrar(BaseClerk)`:
  - `open_session(session_id, min_reputation)` → MSG1
  - `verify_identity(attestation: MSG2)` → VerificationResult (check DID, signature, reputation ≥ floor)
  - `check_quorum(session_id)` → bool (all required roles present: ≥1 speaker, ≥1 regulator, ≥1 codifier, ≥N producers)
  - `admit_agent(session_id, agent_did)` → bool

### Module: `oasis/governance/clerks/speaker.py`
- [ ] P6.3 — `Speaker(BaseClerk)`:
  - `receive_proposal(session_id, proposal: MSG3)` → ProposalResult (validate DAG, budget)
  - `open_straw_poll(session_id)` → StrawPollConfig
  - `collect_straw_poll(session_id, ballots)` → StrawPollSummary
  - `open_deliberation_round(session_id, round_num)` → RoundConfig (randomized speaking order)
  - `close_deliberation_round(session_id, round_num)` → RoundSummary
  - `open_voting(session_id)` → VotingConfig
  - `tabulate_votes(session_id, ballots)` → VotingResult (delegates to CopelandVoting)
  - `check_coordination(session_id)` → CoordinationReport (Kendall τ between straw poll and final vote)
  - `issue_approval(session_id, spec_id)` → MSG7 (Speaker's signature half)

### Module: `oasis/governance/clerks/regulator.py`
- [ ] P6.4 — `Regulator(BaseClerk)`:
  - `publish_evidence(session_id)` → EvidenceBriefing (on-chain performance data before deliberation)
  - `receive_bid(session_id, bid: MSG4)` → BidValidationResult (service registered, code hash, stake ≥ min, PoP tier)
  - `evaluate_bids(session_id)` → MSG5 (approved/rejected, fairness score, compliance flags)
  - `check_fairness(session_id)` → FairnessResult (delegates to fairness.py)
  - `request_reproposal(session_id, reason)` → bool (increments counter, enforces max 2)
  - `co_sign_approval(session_id, spec_id)` → co-signature for MSG7

### Module: `oasis/governance/clerks/codifier.py`
- [ ] P6.5 — `Codifier(BaseClerk)`:
  - `compile_spec(session_id, proposal, approved_bids)` → MSG6 (template parameterization)
  - `run_constitutional_validation(spec)` → ValidationResult (delegates to constitutional.py)
  - `verify_deployment(spec, deployed_contract)` → DeploymentVerificationResult (parameter-by-parameter equality)

### Test Matrix (P6)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_base_clerk.py` | 3 | Authority check passes/fails, abstract methods enforced, clerk DID verified |
| `test_registrar_open.py` | 3 | Session created, MSG1 broadcast, min_reputation set |
| `test_registrar_verify.py` | 5 | Valid identity passes, bad signature fails, low reputation fails, duplicate DID fails, clerk vs producer type |
| `test_registrar_quorum.py` | 4 | Full quorum met, missing role fails, exactly minimum, excess agents ok |
| `test_speaker_proposal.py` | 4 | Valid proposal accepted, cyclic DAG rejected, budget exceeded rejected, timeout enforced |
| `test_speaker_straw_poll.py` | 3 | Poll opened, ballots collected, summary generated |
| `test_speaker_deliberation.py` | 4 | 3 rounds enforced, randomized order, round closure, no 4th round |
| `test_speaker_voting.py` | 4 | Copeland tabulation, quorum check, coordination detection, result stored |
| `test_speaker_approval.py` | 2 | Signature generated, unauthorized action rejected |
| `test_regulator_evidence.py` | 2 | Evidence briefing generated from on-chain data, empty data handled |
| `test_regulator_bids.py` | 5 | Valid bid accepted, low stake rejected, wrong PoP tier rejected, unregistered service rejected, code hash mismatch |
| `test_regulator_evaluate.py` | 4 | All nodes covered passes, fairness check, CRITICAL flag blocks, compliance report |
| `test_regulator_reproposal.py` | 3 | First re-proposal allowed, second allowed, third rejected (max 2) |
| `test_codifier_compile.py` | 3 | Spec compiled from proposal + bids, template parameterization, all fields populated |
| `test_codifier_validate.py` | 3 | Constitutional validation delegated, pass-through result, failure with structured errors |
| `test_codifier_deploy_verify.py` | 3 | Matching spec passes, mismatched param fails, missing field fails |

**Total: ~45 tests** (some files have multiple scenarios)

---

## P7: Clerks — Layer 2 (LLM Reasoning Module)

**Goal:** Add LLM reasoning capabilities to clerks for judgment calls.

### Module updates: each clerk's `layer2_reason()` implementation
- [ ] P7.1 — `Registrar.layer2_reason()`: Sybil pattern detection (burst registrations, similar profiles)
- [ ] P7.2 — `Speaker.layer2_reason()`: deliberation summarization, convergence/deadlock detection, minority position preservation
- [ ] P7.3 — `Regulator.layer2_reason()`: bid feasibility assessment, coordinated bidding detection, compliance concern flagging, evidence briefing enrichment
- [ ] P7.4 — `Codifier.layer2_reason()`: semantic consistency validation between proposal and spec
- [ ] P7.5 — `LLMInterface` protocol: abstract interface for LLM calls (supports mock for testing)

### Test Matrix (P7)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_llm_interface.py` | 3 | Mock LLM responds, real LLM integration (skipped without API key), error handling |
| `test_registrar_sybil.py` | 3 | Burst detection flags suspicious, normal registration passes, threshold configurable |
| `test_speaker_summarize.py` | 4 | Summary generated, minority positions preserved, convergence detected, deadlock detected |
| `test_regulator_feasibility.py` | 3 | Feasible bid passes, infeasible flagged, coordinated pattern detected |
| `test_codifier_semantic.py` | 3 | Consistent spec passes, semantic mismatch flagged, ambiguous proposal handled |
| `test_layer2_toggle.py` | 3 | LLM disabled returns no advisory, LLM enabled returns advisory, Layer 1 unaffected by Layer 2 |
| `test_layer2_advisory_only.py` | 3 | Layer 2 flags don't override Layer 1 pass, Layer 2 flags don't override Layer 1 fail, advisory attached to decision |
| `test_layer2_determinism.py` | 3 | Same input to Layer 1 always same output, Layer 2 may vary (non-deterministic ok), combined result documented |

**Total: ~25 tests**

---

## P8: Governance API Endpoints

**Goal:** Wire governance modules into FastAPI endpoints.

### Module: `oasis/governance/endpoints.py`
- [ ] P8.1 — Session management routes (create, get state, get messages)
- [ ] P8.2 — Identity routes (request verification, submit attestation)
- [ ] P8.3 — Proposal routes (submit, get details)
- [ ] P8.4 — Deliberation routes (straw poll, discuss, summary)
- [ ] P8.5 — Voting routes (submit ranking, get results)
- [ ] P8.6 — Bidding routes (submit bid, list bids)
- [ ] P8.7 — Regulatory routes (submit decision, get evidence briefing)
- [ ] P8.8 — Codification routes (submit spec, get spec)
- [ ] P8.9 — Approval & deployment routes (dual sign-off, deployment status)
- [ ] P8.10 — Constitution & agent info routes (get params, list agents, reputation history)
- [ ] P8.11 — Replace governance stub endpoints (currently 501) with real implementations in `api.py`

### Test Matrix (P8)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_api_session.py` | 4 | Create session, get state, get messages, invalid session 404 |
| `test_api_identity.py` | 4 | Request verification, submit attestation, bad attestation 400, reputation gate |
| `test_api_proposal.py` | 4 | Submit proposal, get details, invalid DAG 400, budget exceeded 400 |
| `test_api_deliberation.py` | 5 | Submit straw poll, submit discussion, get summary, round limit enforced, speaking order randomized |
| `test_api_voting.py` | 4 | Submit ranking, get results, incomplete ranking 400, quorum check |
| `test_api_bidding.py` | 4 | Submit bid, list bids, invalid bid 400, state gate (must be BIDDING_OPEN) |
| `test_api_regulatory.py` | 3 | Submit decision, get evidence, only regulator can submit |
| `test_api_codification.py` | 3 | Submit spec, get spec, constitutional validation failure |
| `test_api_approval.py` | 3 | Dual sign-off, single signature rejected, deployment status |
| `test_api_constitution.py` | 3 | Get params, list agents, reputation history |
| `test_api_state_gates.py` | 3 | Endpoints reject calls in wrong state (e.g., bid in PROPOSAL_OPEN returns 409) |

**Total: ~40 tests**

---

## P9: Recursive Decomposition

**Goal:** Non-leaf DAG nodes trigger child legislative sessions.

### Module extension: `oasis/governance/dag.py`
- [ ] P9.1 — `trigger_child_session(parent_session_id, parent_node_id, db_path)` — creates a new legislative session linked to the parent
- [ ] P9.2 — Budget conservation enforcement: child session budget ≤ parent node budget
- [ ] P9.3 — Quorum inheritance: same quorum rules at all depths
- [ ] P9.4 — Depth tracking and configurable max depth (prevent infinite recursion)
- [ ] P9.5 — `get_session_tree(root_session_id)` — returns the full session hierarchy

### Test Matrix (P9)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_recursive_trigger.py` | 3 | Non-leaf triggers child, leaf does not trigger, parent_session_id FK set |
| `test_recursive_budget.py` | 3 | Budget conserved, child exceeding parent rejected, multi-child budget split |
| `test_recursive_depth.py` | 3 | Depth 1 ok, depth 2 ok, max depth exceeded rejected |
| `test_recursive_quorum.py` | 2 | Same quorum at depth 0 and depth 1, quorum failure at any depth blocks |
| `test_recursive_tree.py` | 2 | Tree retrieval correct, complex tree with multiple children |
| `test_recursive_api.py` | 2 | API triggers child session on deploy, child session accessible via API |

**Total: ~15 tests**

---

## P10: Integration & E2E

**Goal:** Full pipeline tests that exercise the entire legislative process end-to-end.

### Tests
- [ ] P10.1 — Happy path E2E: 5 producers + 4 clerks walk through all 6 stages → DEPLOYED
- [ ] P10.2 — Failed identity: agent below reputation floor → FAILED at IDENTITY_VERIFICATION
- [ ] P10.3 — Failed proposal: cyclic DAG → FAILED at PROPOSAL_OPEN
- [ ] P10.4 — Re-proposal flow: Regulator rejects → re-proposal → success on 2nd attempt
- [ ] P10.5 — Failed bidding: uncovered task nodes at timeout → FAILED
- [ ] P10.6 — Constitutional violation: budget exceeds cap → FAILED at CODIFICATION
- [ ] P10.7 — Approval timeout: no dual sign-off within window → FAILED
- [ ] P10.8 — Recursive E2E: 3-node DAG with 1 non-leaf → parent DEPLOYED triggers child session → child DEPLOYED
- [ ] P10.9 — Concurrent sessions: two independent sessions running simultaneously
- [ ] P10.10 — Full HTTP E2E: same as P10.1 but via FastAPI TestClient (API-level)
- [ ] P10.11 — Layer 2 toggle E2E: same scenario with LLM on/off, verify Layer 1 results identical
- [ ] P10.12 — Coordination detection E2E: agents submit suspiciously correlated votes → flagged
- [ ] P10.13 — Fairness violation E2E: one producer bids on all tasks → Regulator rejects
- [ ] P10.14 — Message log completeness: verify all MSG1-MSG7 logged in correct order
- [ ] P10.15 — Worked example from paper: replicate the 3-task mission trace from Appendix B.8

### Test Matrix (P10)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_e2e_happy_path.py` | 1 | Full 6-stage pipeline succeeds |
| `test_e2e_failure_modes.py` | 6 | Each failure path (identity, proposal, bidding, constitutional, approval, reproposal exhausted) |
| `test_e2e_recursive.py` | 1 | Recursive decomposition triggers and completes |
| `test_e2e_concurrent.py` | 1 | Two parallel sessions don't interfere |
| `test_e2e_http.py` | 1 | Full pipeline via HTTP API |
| `test_e2e_layer2.py` | 2 | LLM toggle, coordination detection |
| `test_e2e_fairness.py` | 1 | Monopolization blocked by fairness check |
| `test_e2e_audit.py` | 1 | Message log complete and ordered |
| `test_e2e_paper_example.py` | 1 | 3-task worked example from Appendix B.8 replicated |

**Total: ~15 tests** (each is a multi-step scenario)

---

## P11: ZeroClaw Governance Skill

**Goal:** Ship a ZeroClaw skill that registers all governance HTTP tools, enabling producer agents to participate in legislative sessions.

### Deliverable: `skills/metosis-governance/SKILL.toml`
- [ ] P11.1 — Skill metadata (name, description, version, tags)
- [ ] P11.2 — 10 HTTP tools matching the governance API surface:

| Tool | Method | Endpoint | Purpose |
|------|--------|----------|---------|
| `attest_identity` | POST | `/api/governance/sessions/{id}/identity/attest` | Prove identity to Registrar |
| `submit_proposal` | POST | `/api/governance/sessions/{id}/proposals` | Propose DAG decomposition |
| `get_evidence` | GET | `/api/governance/sessions/{id}/regulatory/evidence` | Read Regulator's briefing |
| `submit_straw_poll` | POST | `/api/governance/sessions/{id}/deliberation/straw-poll` | Pre-deliberation preference |
| `discuss` | POST | `/api/governance/sessions/{id}/deliberation/discuss` | Structured debate message |
| `get_deliberation_summary` | GET | `/api/governance/sessions/{id}/deliberation/summary` | Read Speaker's synthesis |
| `cast_vote` | POST | `/api/governance/sessions/{id}/vote` | Full ordinal ranking |
| `submit_bid` | POST | `/api/governance/sessions/{id}/bids` | Bid on a task node |
| `get_session_state` | GET | `/api/governance/sessions/{id}` | Check session state |
| `get_vote_results` | GET | `/api/governance/sessions/{id}/vote/results` | Read Copeland results |

- [ ] P11.3 — `skills/metosis-governance/SKILL.md` — human-readable skill documentation with governance protocol overview and tool usage guide
- [ ] P11.4 — `skills/metosis-governance/README.md` — installation instructions (`zeroclaw skills install ./skills/metosis-governance`)
- [ ] P11.5 — Config example: `allowed_domains = ["localhost:8000"]` in ZeroClaw's `config.toml`

### Test Matrix (P11)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_skill_toml.py` | 3 | TOML parses, all 10 tools present, all tools have kind="http" |
| `test_skill_url_templates.py` | 3 | URL templates contain `{{session_id}}`, no broken placeholders, all endpoints match API |
| `test_skill_tool_args.py` | 4 | Each tool has documented args, required args present, arg descriptions non-empty, no duplicate tool names |

**Total: ~10 tests**

---

## P12: Execution — Schema, Routing & Commitment

**Goal:** Execution branch foundation: tables, task routing from deployed contracts, and stake commitment.

### Module: `oasis/execution/schema.py`
- [ ] P12.1 — `create_execution_tables(db_path)` — DDL for `task_assignment`, `task_commitment`, `task_output`, `output_validation`, `settlement`

### Module: `oasis/execution/router.py`
- [ ] P12.2 — `route_tasks(session_id, db_path)` — after DEPLOYED, read approved bid assignments from `regulatory_decision` and create `task_assignment` rows (one per leaf DAG node per assigned agent)
- [ ] P12.3 — `get_agent_tasks(agent_did, db_path)` — list tasks assigned to an agent (filterable by status)
- [ ] P12.4 — `get_session_tasks(session_id, db_path)` — list all tasks for a deployed session

### Module: `oasis/execution/commitment.py`
- [ ] P12.5 — `commit_to_task(task_id, agent_did, db_path)` — validates agent is assignee, locks stake in `agent_balance`, creates `task_commitment` record, transitions task status pending→committed
- [ ] P12.6 — `validate_commitment(task_id, db_path)` — checks stake is sufficient, agent is active, task is in correct state
- [ ] P12.7 — `release_stake(task_id, db_path)` — unlock stake after settlement (called by settlement module)

### Module: `oasis/config.py`
- [ ] P12.8 — Platform configuration dataclass:
  - `execution_mode: Literal["llm", "synthetic"]`
  - `synthetic_quality: Literal["perfect", "mixed", "adversarial"]`
  - `synthetic_success_rate: float` (default 0.8)
  - `synthetic_latency_ms: Tuple[int, int]` (default (50, 200))
  - `adjudication_llm_enabled: bool` (default False)
  - `freeze_threshold: float`, `coordination_threshold: float`, `sanction_floor: float`
  - `protocol_fee_rate: float` (default 0.02), `insurance_fee_rate: float` (default 0.01)
  - `reputation_alpha: float` (default 0.5), `reputation_neutral: float` (default 0.5)

### Test Matrix (P12)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_execution_schema.py` | 3 | Tables created, idempotent, FK constraints enforced |
| `test_router_basic.py` | 4 | Tasks created from approved bids, one per leaf node, correct assignee, session linkage |
| `test_router_no_deploy.py` | 2 | Routing rejects non-DEPLOYED session, routing rejects session with no regulatory decision |
| `test_commitment_valid.py` | 3 | Stake locked, status transitions to committed, commitment record created |
| `test_commitment_invalid.py` | 4 | Wrong agent rejected, insufficient balance rejected, already committed rejected, inactive agent rejected |
| `test_commitment_release.py` | 2 | Stake released after settlement, double-release prevented |
| `test_config.py` | 3 | Default config valid, config overrides work, invalid mode rejected |
| `test_agent_balance.py` | 4 | Initial balance set, lock reduces available, unlock restores, negative balance prevented |

**Total: ~25 tests**

---

## P13: Execution — Runner, Validator & Endpoints

**Goal:** Task execution dispatcher (LLM + synthetic modes), output validation, and HTTP endpoints.

### Module: `oasis/execution/runner.py`
- [ ] P13.1 — `ExecutionDispatcher` class:
  - `__init__(config, db_path)`
  - `dispatch_task(task_id)` — in LLM mode: transitions task to "executing", waits for agent output via API; in synthetic mode: delegates to synthetic generator
  - `receive_output(task_id, output_data, agent_did)` — stores output, triggers validation
  - `get_task_status(task_id)` → TaskStatus

### Module: `oasis/execution/synthetic.py`
- [ ] P13.2 — `SyntheticGenerator` class:
  - `__init__(config)`
  - `generate_output(task_assignment)` → SyntheticOutput
  - `_perfect_output(task)` — valid schema, correct data, within timeout
  - `_mixed_output(task, success_rate)` — configurable failure modes (timeout, schema mismatch, partial output)
  - `_adversarial_output(task)` — high failure rate, malicious outputs (wrong schema, inflated metrics, contradictory data)

### Module: `oasis/execution/validator.py`
- [ ] P13.3 — `OutputValidator` class:
  - `validate(task_id, output, db_path)` → `ValidationResult(schema_valid, timeout_valid, quality_score, guardian_alert)`
  - `_check_schema(output, expected_schema)` — output matches DAG node output_schema
  - `_check_timeout(latency_ms, timeout_ms)` — within node timeout
  - `_check_quality(output)` — optional quality scoring (placeholder for Guardian dual-scorer)
  - `_emit_guardian_alert(task_id, alert_type, severity)` — writes to `guardian_alert` table if validation fails

### Module: `oasis/execution/endpoints.py`
- [ ] P13.4 — FastAPI execution routes:
  - `GET /api/execution/tasks/{task_id}` — task details + input data
  - `POST /api/execution/tasks/{task_id}/commit` — commit to task
  - `POST /api/execution/tasks/{task_id}/output` — submit output (LLM mode)
  - `GET /api/execution/tasks/{task_id}/status` — task status
  - `GET /api/execution/tasks/{task_id}/settlement` — settlement result
  - `GET /api/execution/sessions/{session_id}/tasks` — list session tasks
  - `GET /api/execution/agents/{agent_did}/tasks` — list agent tasks

### Test Matrix (P13)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_runner_llm_mode.py` | 4 | Task dispatched, status=executing, output received and stored, validation triggered |
| `test_runner_synthetic_mode.py` | 3 | Synthetic output generated without agent interaction, output stored, status=completed |
| `test_synthetic_perfect.py` | 3 | All outputs valid, schema correct, within timeout |
| `test_synthetic_mixed.py` | 4 | ~80% success rate (statistical), failure modes varied, schema mismatches present, timeouts present |
| `test_synthetic_adversarial.py` | 3 | High failure rate, malicious output patterns, guardian alerts generated |
| `test_validator_pass.py` | 3 | Valid output passes all checks, no guardian alert, quality score populated |
| `test_validator_fail.py` | 4 | Schema mismatch detected, timeout detected, quality below threshold, guardian alert emitted |
| `test_api_execution.py` | 7 | Each endpoint returns correct response, state gates enforced (must be committed to submit output), 404 for unknown task |
| `test_execution_state_flow.py` | 4 | Full flow: pending→committed→executing→completed, pending→committed→executing→failed, uncommitted output rejected, frozen task blocks output |

**Total: ~35 tests**

---

## P14: Adjudication — Guardian, Sanctions & Settlement

**Goal:** Detection pipeline, sanction enforcement, settlement formula, and treasury accounting.

### Module: `oasis/adjudication/schema.py`
- [ ] P14.1 — `create_adjudication_tables(db_path)` — DDL for `guardian_alert`, `coordination_flag`, `adjudication_decision`, `agent_balance`, `treasury`

### Module: `oasis/adjudication/guardian.py`
- [ ] P14.2 — `Guardian` class:
  - `__init__(config, db_path)`
  - `process_validation(validation_result)` — if validation failed, create `guardian_alert` with appropriate severity
  - `check_anomaly(task_id, output)` — placeholder for dual-scorer anomaly detection (returns no-op in v1, extensible)
  - `get_alerts(filters)` → List[GuardianAlert]
  - Severity mapping: schema_failure→CRITICAL, timeout→WARNING, quality_below_threshold→WARNING, anomaly→CRITICAL

### Module: `oasis/adjudication/sanctions.py`
- [ ] P14.3 — `SanctionEngine` class:
  - `freeze_agent(agent_did, reason, db_path)` — set agent active=0, block from new tasks
  - `unfreeze_agent(agent_did, db_path)` — reactivate
  - `slash_stake(agent_did, amount, reason, db_path)` — deduct from locked_stake, add to treasury as slash_proceeds
  - `reduce_reputation(agent_did, performance_score, db_path)` — EMA update: `new_rep = λ * old_rep + (1-λ) * performance_score`
  - `get_sanction_history(agent_did)` → List[AdjudicationDecision]

### Module: `oasis/adjudication/settlement.py`
- [ ] P14.4 — `SettlementCalculator` class:
  - `__init__(config)`
  - `settle_task(task_id, db_path)` → SettlementResult:
    1. Compute R_base = bid × (1 - f_protocol - f_insurance)
    2. Compute ψ(ρ) = 1 + α × (ρ - ρ_neutral) / ρ_max
    3. R_task = R_base × min(ψ, 1.0) + treasury_subsidy
    4. Write `settlement` row
    5. Update `agent_balance` (add reward / deduct slash)
    6. Update `reputation_ledger` (EMA)
    7. Write treasury entries (protocol fee, insurance fee, subsidy if applicable)
  - `reputation_multiplier(reputation)` → float
  - `compute_treasury_subsidy(R_base, psi)` → float (premium financed from treasury)

### Module: `oasis/adjudication/treasury.py`
- [ ] P14.5 — `Treasury` class:
  - `__init__(db_path)`
  - `record_fee(task_id, fee_type, amount)` — append to treasury table
  - `record_slash(agent_did, amount)` — append slash_proceeds entry
  - `record_subsidy(task_id, agent_did, amount)` — append reputation_subsidy entry
  - `get_balance()` → float (total inflows - total outflows)
  - `get_summary()` → TreasurySummary (inflows by type, outflows by type, net balance)
  - `get_ledger(filters)` → List[TreasuryEntry]

### Test Matrix (P14)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_adjudication_schema.py` | 3 | Tables created, idempotent, FK constraints |
| `test_guardian_alerts.py` | 5 | Schema failure → CRITICAL alert, timeout → WARNING, quality below threshold → WARNING, anomaly → CRITICAL, valid output → no alert |
| `test_guardian_query.py` | 3 | Filter by severity, filter by agent, filter by task |
| `test_sanction_freeze.py` | 3 | Agent frozen (active=0), frozen agent cannot commit to new tasks, unfreeze restores |
| `test_sanction_slash.py` | 4 | Stake deducted, treasury receives slash_proceeds, insufficient stake partial slash, sanction history recorded |
| `test_sanction_reputation.py` | 3 | EMA update correct, λ=0.8 default, reputation_ledger appended |
| `test_settlement_success.py` | 4 | Full settlement computed, fees deducted, reputation multiplier applied, balance updated |
| `test_settlement_formula.py` | 4 | ψ(0)=0.75, ψ(neutral)=1.0, ψ(max)=1.25, treasury subsidy for ψ>1.0 |
| `test_settlement_slash.py` | 2 | Failed task → slash, frozen task → slash |
| `test_treasury_accounting.py` | 4 | Fees recorded, slash recorded, subsidy recorded, balance = inflows - outflows |

**Total: ~35 tests**

---

## P15: Adjudication — Override Panel, Endpoints & LLM Toggle

**Goal:** Deterministic rule engine (Layer 1), optional LLM adjudicator (Layer 2), coordination detection wrapper, and HTTP endpoints.

### Module: `oasis/adjudication/override_panel.py`
- [ ] P15.1 — `OverridePanel` class (two-layer, same pattern as clerks):
  - `__init__(config, db_path, llm_enabled=False)`
  - `layer1_evaluate(alert_or_flag)` → DeterministicDecision:
    - Guardian alert + quality < freeze_threshold → FREEZE
    - Guardian alert + quality ≥ freeze_threshold but < warn_threshold → NEEDS_REVIEW
    - Coordination flag + kendall_tau > coordination_threshold → FLAG_AND_DELAY
    - Performance: reputation < sanction_floor AND consecutive_failures ≥ 3 → SLASH
    - Otherwise → DISMISS
  - `layer2_evaluate(context, layer1_decision)` → LLMAdvisory (only when layer1 returns NEEDS_REVIEW):
    - Evaluates borderline output quality
    - Analyzes deliberation transcripts for genuine vs. coincidental agreement
    - Evaluates appeal evidence
  - `decide(alert_or_flag)` → AdjudicationDecision (combines Layer 1 + Layer 2)
  - `process_batch(alerts, flags)` → List[AdjudicationDecision] (batch processing for efficiency)

### Module: `oasis/adjudication/coordination.py`
- [ ] P15.2 — `CoordinationDetector` class:
  - `detect_voting_coordination(session_id, db_path)` — wraps `voting.kendall_tau` and `voting.coordination_detection` from P3
  - `detect_bidding_coordination(session_id, db_path)` — Jaccard overlap on bid targets
  - `flag_pairs(session_id, db_path)` → List[CoordinationFlag] — writes to `coordination_flag` table

### Module: `oasis/adjudication/endpoints.py`
- [ ] P15.3 — FastAPI adjudication routes:
  - `GET /api/adjudication/alerts` — list alerts (query params: severity, agent_did, task_id)
  - `GET /api/adjudication/alerts/{alert_id}` — alert details
  - `GET /api/adjudication/flags` — list coordination flags (query params: session_id, agent_did)
  - `GET /api/adjudication/decisions` — list decisions (query params: agent_did, decision_type)
  - `GET /api/adjudication/decisions/{decision_id}` — decision details
  - `GET /api/adjudication/agents/{agent_did}/balance` — agent balance
  - `GET /api/adjudication/agents/{agent_did}/sanctions` — sanction history
  - `GET /api/adjudication/treasury` — treasury summary
  - `GET /api/adjudication/treasury/ledger` — treasury transaction ledger

### Test Matrix (P15)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_override_layer1.py` | 5 | CRITICAL alert → freeze, borderline → needs_review, coordination flag → flag_and_delay, sustained failure → slash, clean record → dismiss |
| `test_override_layer2.py` | 4 | LLM disabled returns no advisory, LLM enabled evaluates borderline, advisory doesn't override Layer 1 freeze, advisory attached to decision |
| `test_override_batch.py` | 2 | Batch processes multiple alerts, decisions stored in DB |
| `test_coordination_voting.py` | 3 | Correlated pair flagged, uncorrelated pair not flagged, threshold configurable |
| `test_coordination_bidding.py` | 3 | Overlapping bid targets flagged, diverse bids not flagged, Jaccard computed correctly |
| `test_api_adjudication.py` | 8 | Each endpoint returns correct response, filters work, 404 for unknown entities |

**Total: ~25 tests**

---

## P16: ZeroClaw Execution Skill + Full Cross-Branch E2E

**Goal:** Update the ZeroClaw skill with 5 execution tools, and run full cross-branch E2E tests covering legislation → execution → adjudication.

### Deliverable: Updated `skills/metosis-governance/SKILL.toml`
- [ ] P16.1 — Add 5 execution tools to existing 10 governance tools (total 15):

| Tool | Method | Endpoint | Purpose |
|------|--------|----------|---------|
| `get_task` | GET | `/api/execution/tasks/{task_id}` | Retrieve assigned task details |
| `submit_commitment` | POST | `/api/execution/tasks/{task_id}/commit` | Commit to task (locks stake) |
| `submit_task_output` | POST | `/api/execution/tasks/{task_id}/output` | Submit completed output |
| `get_task_status` | GET | `/api/execution/tasks/{task_id}/status` | Check execution status |
| `get_settlement` | GET | `/api/execution/tasks/{task_id}/settlement` | Get settlement result |

- [ ] P16.2 — Update SKILL.md with execution tool documentation and full lifecycle guide

### Cross-Branch E2E Tests
- [ ] P16.3 — Full lifecycle E2E: legislate → deploy → route tasks → commit → execute (LLM mode) → validate → settle → reputation update
- [ ] P16.4 — Full lifecycle E2E (synthetic mode): same pipeline but with synthetic outputs, verify settlement and reputation
- [ ] P16.5 — Guardian freeze E2E: bad output → guardian alert → override panel freeze → stake slash → reputation reduction
- [ ] P16.6 — Coordination detection E2E: correlated votes → flag → delay proposal → adjudication decision
- [ ] P16.7 — Treasury balance E2E: run 10 tasks, verify fees + slashing + subsidies balance correctly
- [ ] P16.8 — Mixed execution mode E2E: switch between LLM and synthetic mid-experiment via config
- [ ] P16.9 — Scale smoke test: 50 agents, 20 tasks, verify no deadlocks or data races

### Test Matrix (P16)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_skill_execution_tools.py` | 3 | 5 new tools present in TOML, URL templates correct, args documented |
| `test_skill_full_surface.py` | 2 | All 15 tools present, no duplicates |
| `test_e2e_full_lifecycle_llm.py` | 1 | Complete 3-branch pipeline (LLM mode) |
| `test_e2e_full_lifecycle_synthetic.py` | 1 | Complete 3-branch pipeline (synthetic mode) |
| `test_e2e_guardian_freeze.py` | 1 | Bad output triggers freeze + slash pipeline |
| `test_e2e_coordination.py` | 1 | Correlated votes flagged and delayed |
| `test_e2e_treasury.py` | 1 | Treasury accounting correct over multiple tasks |
| `test_e2e_mode_switch.py` | 1 | Config switch between LLM/synthetic works mid-run |
| `test_e2e_scale.py` | 1 | 50 agents × 20 tasks completes without errors |

**Total: ~12 tests** (each E2E is a multi-step scenario)

---

## P17: Observatory — Event Bus, WebSocket & Web Dashboard

**Goal:** Real-time observability for experiment operators — event bus, WebSocket stream, REST aggregation endpoints, and a self-contained web dashboard.

### Module: `oasis/observatory/schema.py`
- [ ] P17.1 — `create_observatory_tables(db_path)` — DDL for `event_log`

### Module: `oasis/observatory/events.py`
- [ ] P17.2 — `EventType` enum covering all categories (session, identity, legislative, execution, adjudication, system)
- [ ] P17.3 — `Event` dataclass: event_id, event_type, timestamp, session_id, agent_did, payload, sequence_number
- [ ] P17.4 — `serialize_event(event)` → JSON string for WebSocket transmission

### Module: `oasis/observatory/event_bus.py`
- [ ] P17.5 — `EventBus` class (singleton):
  - `__init__(db_path)`
  - `publish(event)` — assigns monotonic sequence_number, persists to `event_log`, notifies all subscribers
  - `subscribe(callback, filter=None)` → subscription_id
  - `unsubscribe(subscription_id)`
  - `replay(since_sequence=0, event_types=None, session_id=None, agent_did=None, limit=100)` → List[Event]
  - Internal: asyncio queue per subscriber, sequence counter (atomic)
- [ ] P17.6 — Instrument all state-mutating operations across governance, execution, and adjudication modules to call `event_bus.publish()` (decorator or explicit calls at each mutation point)

### Module: `oasis/observatory/websocket.py`
- [ ] P17.7 — `websocket_events(ws, filters)` — FastAPI WebSocket handler:
  - Parse filter query params: `types` (glob patterns), `session_id`, `agent_did`
  - Subscribe to EventBus with filter
  - Stream events as JSON messages
  - Backpressure: if client queue exceeds 1000 events, drop oldest (log warning)
  - On disconnect: unsubscribe

### Module: `oasis/observatory/endpoints.py`
- [ ] P17.8 — Observatory REST endpoints:
  - `GET /api/observatory/summary` — aggregate query: count sessions by state, count agents by status, tasks in progress, treasury balance, active alert count
  - `GET /api/observatory/agents/leaderboard` — join agent_registry + agent_balance + reputation_ledger, sort by configurable metric
  - `GET /api/observatory/reputation/timeseries` — query reputation_ledger for time-series data (query params: agent_did, since, until)
  - `GET /api/observatory/treasury/timeseries` — running balance over time from treasury table
  - `GET /api/observatory/events` — paginated event_log query (query params: type glob, session_id, agent_did, since, limit, offset)
  - `GET /api/observatory/sessions/timeline` — session state history for Gantt rendering
  - `GET /api/observatory/execution/heatmap` — pivot task_assignment by agent x task, return status matrix

### Module: `oasis/observatory/dashboard.py`
- [ ] P17.9 — `GET /dashboard` handler serving a self-contained HTML page:
  - Single HTML file with inline CSS + JS (no build step, no npm)
  - Chart.js (or lightweight alternative) bundled inline for charts
  - Connects to `WS /ws/events` on load
  - 8 panels: session timeline, agent leaderboard, reputation chart, treasury gauge, fairness monitor, event log, execution heatmap, alert panel
  - Auto-reconnect on WebSocket disconnect
  - Responsive layout (CSS grid)
  - Dark theme (suitable for monitoring)

### Test Matrix (P17)
| Test File | Tests | What it validates |
|-----------|-------|-------------------|
| `test_event_types.py` | 3 | All event types defined, serialization round-trip, sequence_number monotonic |
| `test_event_bus_publish.py` | 3 | Event published and persisted, subscriber notified, filter applied correctly |
| `test_event_bus_replay.py` | 3 | Replay from sequence, replay with type filter, replay with session filter |
| `test_websocket_stream.py` | 3 | Events streamed to connected client, filter query params work, disconnect cleans up |
| `test_websocket_backpressure.py` | 2 | Slow client queue capped at 1000, events still persisted to DB |
| `test_api_summary.py` | 2 | Summary returns correct aggregate counts, empty DB returns zeros |
| `test_api_leaderboard.py` | 2 | Agents ranked correctly, sortable by different metrics |
| `test_api_timeseries.py` | 2 | Reputation timeseries returns data points, treasury timeseries computes running balance |

**Total: ~20 tests**

---

## Dependency Graph

```
P0 (Test Infra)
 │
 ▼
P1 (Schema) ──────────────────────────────────────┐
 │                                                  │
 ▼                                                  ▼
P2 (State Machine)    P3 (Voting & Fairness)    P5 (Messages)
 │                     │                          │
 ▼                     ▼                          ▼
P4 (DAG & Constitutional) ◄──────────────────────┘
 │
 ▼
P6 (Clerks Layer 1) ◄── P3, P4, P5
 │
 ├──► P7 (Clerks Layer 2)
 │
 ▼
P8 (Governance API) ◄── P2, P6
 │
 ▼
P9 (Recursive Decomposition) ◄── P2, P4
 │
 ▼
P10 (Legislative E2E) ◄── P0–P9
 │
 ▼
P11 (ZeroClaw Gov Skill) ◄── P8
 │
 ▼
P12 (Execution Schema/Routing/Commitment) ◄── P1, P8, P10
 │
 ▼
P13 (Execution Runner/Validator/Endpoints) ◄── P12
 │
 ▼
P14 (Adjudication Guardian/Sanctions/Settlement) ◄── P3, P12, P13
 │
 ▼
P15 (Adjudication Override Panel/Endpoints/LLM) ◄── P14
 │
 ▼
P16 (ZeroClaw Execution Skill + Cross-Branch E2E) ◄── ALL (P0–P15)
 │
 ▼
P17 (Observatory: Event Bus, WebSocket, Dashboard) ◄── P16 (needs all modules instrumented)
```

**Parallelizable within the legislative branch:** P2, P3, P5 can be built concurrently after P1. P4 depends on P3. P6 depends on P3, P4, P5. P7, P8, P9 are parallelizable after P6.

**Sequential across branches:** Execution (P12-P13) requires a DEPLOYED legislative session. Adjudication (P14-P15) requires execution validation results. P16 is the cross-branch capstone. P17 instruments all modules.

---

## Implementation Sequencing (Recommended)

| Order | Phases | Rationale |
|-------|--------|-----------|
| 1 | P0 | Must have test infra first |
| 2 | P1 | Schema is foundation for everything |
| 3 | P2 + P3 + P5 (parallel) | Independent modules, all depend only on P1 |
| 4 | P4 | Depends on P3 (fairness) |
| 5 | P6 | Depends on P3 + P4 + P5 |
| 6 | P7 + P8 + P9 (parallel) | P7 extends P6, P8 wires P6, P9 extends P4 |
| 7 | P10 + P11 (parallel) | Legislative E2E + governance skill |
| 8 | P12 | Execution foundation (schema, routing, commitment) |
| 9 | P13 | Execution logic (runner, validator, synthetic, endpoints) |
| 10 | P14 | Adjudication foundation (guardian, sanctions, settlement, treasury) |
| 11 | P15 | Adjudication logic (override panel, coordination, endpoints, LLM toggle) |
| 12 | P16 | Skill update + cross-branch E2E (capstone) |
| 13 | P17 | Observatory: event bus, WebSocket, dashboard |
