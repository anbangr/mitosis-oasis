"""Tests for invalid DAG specifications."""
from oasis.governance.dag import DAGEdge, DAGNode, DAGSpec, validate_dag


def _node(nid: str, budget: float = 100.0, **kw) -> DAGNode:
    return DAGNode(
        node_id=nid, label=nid, service_id=f"svc-{nid}",
        token_budget=budget, timeout_ms=60000, **kw,
    )


def test_cycle_detected():
    """A→B→C→A cycle should be detected."""
    dag = DAGSpec(
        nodes=[_node("A"), _node("B"), _node("C")],
        edges=[
            DAGEdge("A", "B"),
            DAGEdge("B", "C"),
            DAGEdge("C", "A"),
        ],
    )
    result = validate_dag(dag)
    assert not result.valid
    assert any("cycle" in e.lower() for e in result.errors)


def test_no_root():
    """Every node has an incoming edge — no root."""
    dag = DAGSpec(
        nodes=[_node("A"), _node("B")],
        edges=[
            DAGEdge("A", "B"),
            DAGEdge("B", "A"),
        ],
    )
    result = validate_dag(dag)
    assert not result.valid


def test_no_terminal():
    """Every node has an outgoing edge — no terminal (implies cycle)."""
    dag = DAGSpec(
        nodes=[_node("A"), _node("B")],
        edges=[
            DAGEdge("A", "B"),
            DAGEdge("B", "A"),
        ],
    )
    result = validate_dag(dag)
    assert not result.valid


def test_orphan_node():
    """An orphan node not connected by any edge in a multi-node DAG."""
    dag = DAGSpec(
        nodes=[_node("A", 500), _node("B", 200), _node("orphan", 50)],
        edges=[DAGEdge("A", "B")],
    )
    result = validate_dag(dag)
    assert not result.valid
    assert any("orphan" in e.lower() for e in result.errors)


def test_empty_dag():
    """An empty DAG with no nodes should fail."""
    dag = DAGSpec(nodes=[], edges=[])
    result = validate_dag(dag)
    assert not result.valid
    assert any("no nodes" in e.lower() for e in result.errors)
