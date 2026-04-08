"""Tests for valid DAG specifications."""
from oasis.governance.dag import DAGEdge, DAGNode, DAGSpec, validate_dag


def _node(nid: str, budget: float = 100.0, **kw) -> DAGNode:
    return DAGNode(
        node_id=nid, label=nid, service_id=f"svc-{nid}",
        token_budget=budget, timeout_ms=60000, **kw,
    )


def test_linear_chain():
    """A→B→C linear chain is a valid DAG."""
    dag = DAGSpec(
        nodes=[_node("A", 500), _node("B", 250), _node("C", 100)],
        edges=[
            DAGEdge("A", "B"),
            DAGEdge("B", "C"),
        ],
    )
    result = validate_dag(dag)
    assert result.valid, result.errors
    assert result.topological_order == ["A", "B", "C"]


def test_diamond():
    """Diamond: A→B, A→C, B→D, C→D is valid."""
    dag = DAGSpec(
        nodes=[
            _node("A", 600),
            _node("B", 200),
            _node("C", 200),
            _node("D", 100),
        ],
        edges=[
            DAGEdge("A", "B"),
            DAGEdge("A", "C"),
            DAGEdge("B", "D"),
            DAGEdge("C", "D"),
        ],
    )
    result = validate_dag(dag)
    assert result.valid, result.errors
    assert result.topological_order[0] == "A"
    assert result.topological_order[-1] == "D"


def test_single_node():
    """A single node with no edges is a valid (trivial) DAG."""
    dag = DAGSpec(nodes=[_node("solo", 50)])
    result = validate_dag(dag)
    assert result.valid, result.errors
    assert result.topological_order == ["solo"]


def test_complex_six_node():
    """Complex 6-node DAG with multiple paths."""
    dag = DAGSpec(
        nodes=[
            _node("A", 1000),
            _node("B", 300),
            _node("C", 400),
            _node("D", 100),
            _node("E", 100),
            _node("F", 50),
        ],
        edges=[
            DAGEdge("A", "B"),
            DAGEdge("A", "C"),
            DAGEdge("B", "D"),
            DAGEdge("B", "E"),
            DAGEdge("C", "E"),
            DAGEdge("C", "F"),
        ],
    )
    result = validate_dag(dag)
    assert result.valid, result.errors
    assert len(result.topological_order) == 6
    # A must come before all its descendants
    order = result.topological_order
    assert order.index("A") < order.index("B")
    assert order.index("A") < order.index("C")
    assert order.index("B") < order.index("D")
