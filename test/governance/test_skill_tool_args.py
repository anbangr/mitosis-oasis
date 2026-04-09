"""P11 tests: Tool argument documentation validation for SKILL.toml."""
from pathlib import Path

import tomli


SKILL_TOML = Path(__file__).resolve().parents[2] / "skills" / "metosis-governance" / "SKILL.toml"


def _load_skill():
    with open(SKILL_TOML, "rb") as f:
        return tomli.load(f)


# ---------- Test 1: Each tool has documented args ----------

def test_each_tool_has_args():
    """Every tool must have at least one documented argument."""
    data = _load_skill()
    for tool in data["tools"]:
        args = tool.get("args", [])
        assert len(args) > 0, (
            f"Tool {tool['name']!r} has no documented args"
        )


# ---------- Test 2: Required args present ----------

# Minimum required args for each tool
REQUIRED_ARGS = {
    "attest_identity": {"session_id", "agent_did", "signature", "reputation_score"},
    "submit_proposal": {"session_id", "proposer_did", "dag_spec", "token_budget_total", "deadline_ms"},
    "get_evidence": {"session_id"},
    "submit_straw_poll": {"session_id", "ballots"},
    "discuss": {"session_id", "agent_did", "round_number", "message"},
    "get_deliberation_summary": {"session_id"},
    "cast_vote": {"session_id", "ballots"},
    "submit_bid": {
        "session_id", "task_node_id", "bidder_did", "service_id",
        "proposed_code_hash", "stake_amount", "estimated_latency_ms",
        "pop_tier_acceptance",
    },
    "get_session_state": {"session_id"},
    "get_vote_results": {"session_id"},
    # Execution tools
    "get_task": {"task_id"},
    "submit_commitment": {"task_id", "agent_did"},
    "submit_task_output": {"task_id", "agent_did", "output_data"},
    "get_task_status": {"task_id"},
    "get_settlement": {"task_id"},
}


def test_required_args_present():
    """Each tool must list its required arguments with required=true."""
    data = _load_skill()
    for tool in data["tools"]:
        name = tool["name"]
        args = tool.get("args", [])
        required_names = {a["name"] for a in args if a.get("required", False)}
        expected = REQUIRED_ARGS.get(name, set())
        missing = expected - required_names
        assert not missing, (
            f"Tool {name!r}: missing required args {missing}"
        )


# ---------- Test 3: Arg descriptions non-empty ----------

def test_arg_descriptions_non_empty():
    """Every argument must have a non-empty description string."""
    data = _load_skill()
    for tool in data["tools"]:
        for arg in tool.get("args", []):
            desc = arg.get("description", "")
            assert isinstance(desc, str) and len(desc.strip()) > 0, (
                f"Tool {tool['name']!r}, arg {arg['name']!r}: "
                f"description is empty or missing"
            )


# ---------- Test 4: No duplicate tool names ----------

def test_no_duplicate_tool_names():
    """Tool names must be unique across the entire SKILL.toml."""
    data = _load_skill()
    names = [t["name"] for t in data["tools"]]
    seen = set()
    duplicates = set()
    for n in names:
        if n in seen:
            duplicates.add(n)
        seen.add(n)
    assert not duplicates, f"Duplicate tool names: {duplicates}"
