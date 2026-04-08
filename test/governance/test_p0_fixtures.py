"""P0 — Validate governance test fixtures are wired correctly.

These tests verify the fixture plumbing only.  They use ``db_path``
(the lightweight fixture that does NOT call create_governance_tables)
and the sample data fixtures, which are pure dicts with no DB dependency.
"""
from pathlib import Path


def test_db_path_is_tmp(db_path: Path):
    """db_path fixture produces a path under tmp_path."""
    assert "test_governance.db" in str(db_path)
    # File should not exist yet — fixtures don't create it
    assert not db_path.exists()


def test_sample_agents_structure(sample_agents: dict):
    """sample_agents fixture provides 5 producers + 4 clerks."""
    assert len(sample_agents["producers"]) == 5
    assert len(sample_agents["clerks"]) == 4
    for p in sample_agents["producers"]:
        assert p["agent_type"] == "producer"
        assert p["agent_did"].startswith("did:mock:producer-")
    for c in sample_agents["clerks"]:
        assert c["agent_type"] == "clerk"
        assert c["clerk_role"] in ("registrar", "speaker", "regulator", "codifier")


def test_sample_constitution_params(sample_constitution: dict):
    """sample_constitution has the expected parameter set."""
    expected_keys = {
        "budget_cap_max", "budget_cap_min", "quorum_threshold",
        "max_deliberation_rounds", "reputation_floor",
        "fairness_hhi_threshold", "proposal_deadline_max_ms",
        "voting_method", "max_dag_depth", "max_dag_nodes",
    }
    assert set(sample_constitution.keys()) == expected_keys
    assert sample_constitution["quorum_threshold"] == 0.51
    assert sample_constitution["max_deliberation_rounds"] == 3


def test_sample_dag_structure(sample_dag: dict):
    """sample_dag is a valid 3-node, 2-edge DAG."""
    nodes = sample_dag["nodes"]
    edges = sample_dag["edges"]
    assert len(nodes) == 3
    assert len(edges) == 2
    node_ids = {n["node_id"] for n in nodes}
    assert node_ids == {"root", "task-a", "task-b"}
    for e in edges:
        assert e["from_node_id"] in node_ids
        assert e["to_node_id"] in node_ids
