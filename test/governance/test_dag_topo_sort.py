"""Tests for topological sort."""
import pytest

from oasis.governance.dag import (
    CycleError,
    DAGEdge,
    DAGNode,
    DAGSpec,
    topological_sort,
)


def _node(nid: str) -> DAGNode:
    return DAGNode(
        node_id=nid, label=nid, service_id=f"svc-{nid}",
        token_budget=100.0, timeout_ms=60000,
    )


def test_correct_ordering():
    """Topological order respects all edges: A→B→C."""
    dag = DAGSpec(
        nodes=[_node("A"), _node("B"), _node("C")],
        edges=[DAGEdge("A", "B"), DAGEdge("B", "C")],
    )
    order = topological_sort(dag)
    assert order == ["A", "B", "C"]


def test_diamond_ordering():
    """Diamond DAG: A before B,C; B,C before D."""
    dag = DAGSpec(
        nodes=[_node("A"), _node("B"), _node("C"), _node("D")],
        edges=[
            DAGEdge("A", "B"),
            DAGEdge("A", "C"),
            DAGEdge("B", "D"),
            DAGEdge("C", "D"),
        ],
    )
    order = topological_sort(dag)
    assert order[0] == "A"
    assert order[-1] == "D"
    assert order.index("A") < order.index("B")
    assert order.index("A") < order.index("C")


def test_cycle_raises_error():
    """Cycle in the DAG should raise CycleError."""
    dag = DAGSpec(
        nodes=[_node("A"), _node("B"), _node("C")],
        edges=[
            DAGEdge("A", "B"),
            DAGEdge("B", "C"),
            DAGEdge("C", "A"),
        ],
    )
    with pytest.raises(CycleError):
        topological_sort(dag)
