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
| **Total** | | | **~310 tests** | **~5,200** |

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
P8 (API Endpoints) ◄── P2, P6
 │
 ▼
P9 (Recursive Decomposition) ◄── P2, P4
 │
 ▼
P10 (Integration & E2E) ◄── ALL
```

**Parallelizable:** P2, P3, P5 can be built concurrently after P1. P4 depends on P3 (fairness). P6 depends on P3, P4, P5. P7 can start after P6. P8 can start after P6. P9 can start after P4.

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
| 7 | P10 | Integration depends on all above |
