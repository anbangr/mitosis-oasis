"""E2E Layer 2 tests — LLM toggle and coordination detection."""
from __future__ import annotations

import sqlite3

from oasis.governance.clerks.llm_interface import MockLLM
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.clerks.regulator import Regulator
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import DAGProposal, IdentityAttestation
from oasis.governance.state_machine import LegislativeState, LegislativeStateMachine

from .conftest import DEFAULT_DAG, drive_session_to_deployed


class TestLayer2:

    def test_llm_toggle_results_identical(self, e2e_db, producers):
        """Same scenario with LLM on/off — Layer 1 results identical, Layer 2 fires when on."""
        # Run without LLM
        result_off = drive_session_to_deployed(
            e2e_db, producers,
            session_id="layer2-off",
            llm_enabled=False,
        )

        # Run with MockLLM
        mock_llm = MockLLM(default_response="No issues detected.")
        result_on = drive_session_to_deployed(
            e2e_db, producers,
            session_id="layer2-on",
            llm_enabled=True,
            llm=mock_llm,
        )

        # Both reach DEPLOYED
        assert result_off["sm"].current_state == LegislativeState.DEPLOYED
        assert result_on["sm"].current_state == LegislativeState.DEPLOYED

        # Same number of transitions
        history_off = result_off["sm"].history()
        history_on = result_on["sm"].history()
        assert len(history_off) == len(history_on)

        # Layer 1 outcomes identical: same state sequence
        states_off = [h.to_state for h in history_off]
        states_on = [h.to_state for h in history_on]
        assert states_off == states_on

        # Explicitly invoke Layer 2 reasoning to verify it fires when enabled
        db = str(e2e_db)

        # Use Regulator's layer2 since it always calls the LLM
        regulator_on = Regulator(
            db_path=db, clerk_did="did:oasis:clerk-regulator",
            llm_enabled=True, llm=mock_llm,
        )
        regulator_off = Regulator(
            db_path=db, clerk_did="did:oasis:clerk-regulator",
            llm_enabled=False,
        )

        # Layer 2 with LLM disabled returns None
        l2_off = regulator_off.layer2_reason({
            "session_id": "layer2-off",
            "bid_set": [{"bidder_did": "test", "stake_amount": 0.5,
                         "estimated_latency_ms": 5000, "task_node_id": "n1"}],
        })
        assert l2_off is None

        # Layer 2 with LLM enabled returns a result
        l2_on = regulator_on.layer2_reason({
            "session_id": "layer2-on",
            "bid_set": [{"bidder_did": "test", "stake_amount": 0.5,
                         "estimated_latency_ms": 5000, "task_node_id": "n1"}],
            "fairness_score": 0.8,
        })
        assert l2_on is not None
        assert "feasibility_concerns" in l2_on

        # Verify LLM was actually called
        assert len(mock_llm.call_log) > 0

    def test_coordination_detection_e2e(self, e2e_db, producers):
        """Agents submit suspiciously correlated votes → flagged."""
        sid = "coord-detect"
        db = str(e2e_db)

        conn = sqlite3.connect(db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO legislative_session (session_id, state, epoch, mission_budget_cap) "
            "VALUES (?, 'SESSION_INIT', 0, 1000.0)",
            (sid,),
        )
        conn.commit()
        conn.close()

        registrar = Registrar(db_path=db, clerk_did="did:oasis:clerk-registrar")
        registrar.open_session(sid, 0.1)

        sm = LegislativeStateMachine(sid, db)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)

        for p in producers:
            att = IdentityAttestation(
                session_id=sid, agent_did=p["agent_did"],
                signature="sig", reputation_score=0.5, agent_type="producer",
            )
            registrar.verify_identity(att)

        conn = sqlite3.connect(db)
        conn.execute("PRAGMA foreign_keys = ON")
        for p in producers:
            conn.execute(
                "INSERT INTO message_log (session_id, msg_type, sender_did, payload) "
                "VALUES (?, 'IdentityVerificationResponse', ?, '{}')",
                (sid, p["agent_did"]),
            )
        conn.commit()
        conn.close()

        sm.transition(LegislativeState.PROPOSAL_OPEN)

        speaker = Speaker(db_path=db, clerk_did="did:oasis:clerk-speaker")

        # Submit two proposals with unique node IDs
        for pname in ["prop-alpha", "prop-beta"]:
            dag_spec = {
                "nodes": [
                    {"node_id": f"{pname}-n1", "label": f"{pname} T1", "service_id": "svc1",
                     "pop_tier": 1, "token_budget": 500.0, "timeout_ms": 60000},
                    {"node_id": f"{pname}-n2", "label": f"{pname} T2", "service_id": "svc2",
                     "pop_tier": 1, "token_budget": 200.0, "timeout_ms": 60000},
                ],
                "edges": [{"from_node_id": f"{pname}-n1", "to_node_id": f"{pname}-n2"}],
            }
            proposal = DAGProposal(
                session_id=sid, proposer_did=producers[0]["agent_did"],
                dag_spec=dag_spec, rationale=f"{pname} test",
                token_budget_total=700.0, deadline_ms=60000,
            )
            speaker.receive_proposal(sid, proposal)

        # Get proposal IDs
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        prop_rows = conn.execute(
            "SELECT proposal_id FROM proposal WHERE session_id = ? ORDER BY created_at",
            (sid,),
        ).fetchall()
        conn.close()
        candidates = [r["proposal_id"] for r in prop_rows]

        # Straw poll: all agents have IDENTICAL rankings (max coordination)
        straw_ballots = {
            p["agent_did"]: list(candidates)
            for p in producers
        }
        speaker.collect_straw_poll(sid, straw_ballots)

        # Final vote: identical rankings (same as straw poll)
        vote_ballots = {
            p["agent_did"]: list(candidates)
            for p in producers
        }
        speaker.tabulate_votes(sid, vote_ballots)

        # Check coordination detection
        coord_result = speaker.check_coordination(sid)
        assert coord_result["flagged"] is True
        assert coord_result["avg_tau"] >= 0.8
