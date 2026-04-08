"""Tests for DAG budget conservation."""
from oasis.governance.dag import DAGEdge, DAGNode, DAGSpec, validate_dag


def _node(nid: str, budget: float = 100.0, **kw) -> DAGNode:
    return DAGNode(
        node_id=nid, label=nid, service_id=f"svc-{nid}",
        token_budget=budget, timeout_ms=60000, **kw,
    )


def test_budget_conservation_passes():
    """Children budgets sum to <= parent budget."""
    dag = DAGSpec(
        nodes=[_node("A", 500), _node("B", 200), _node("C", 300)],
        edges=[DAGEdge("A", "B"), DAGEdge("A", "C")],
    )
    result = validate_dag(dag)
    assert result.valid, result.errors


def test_child_exceeds_parent():
    """Children budgets exceeding parent should fail."""
    dag = DAGSpec(
        nodes=[_node("A", 100), _node("B", 200), _node("C", 300)],
        edges=[DAGEdge("A", "B"), DAGEdge("A", "C")],
    )
    result = validate_dag(dag)
    assert not result.valid
    assert any("budget" in e.lower() for e in result.errors)


def test_zero_budget_fails():
    """A node with zero budget should fail."""
    dag = DAGSpec(
        nodes=[_node("A", 500), _node("B", 0)],
        edges=[DAGEdge("A", "B")],
    )
    result = validate_dag(dag)
    assert not result.valid
    assert any("non-positive" in e.lower() for e in result.errors)
