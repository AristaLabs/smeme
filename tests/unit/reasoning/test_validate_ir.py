"""IR structural validation (B0.5-lite)."""

from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    QNRMetadata,
    QuestionData,
)
from smeme.reasoning.ir.types import (
    DEFAULT_GUARD_EXPR,
    IR,
    IR_FORMAT_VERSION,
    Guard,
    IREdge,
    IRNode,
    IRNodeKind,
    IRQuestionShape,
)
from smeme.reasoning.ir.validate import validate_ir
from smeme.reasoning.qnr_bridge import compile_qnr_to_ir

_Q_RADIO = IRQuestionShape(qtype="radio", options=("A", "B"))


def test_validate_ir_accepts_compiled_graph():
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Pick",
                    type="radio",
                    options=["Yes", "No"],
                    required=True,
                ),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="Out A", summary="a"),
            ),
            GraphNode(
                id="c2",
                type="conclusion",
                data=ConclusionData(title="Out B", summary="b"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=QNRMetadata(title="v"),
    )
    ir = compile_qnr_to_ir(g)
    report = validate_ir(ir)
    assert report.valid
    assert report.errors == ()

    g2 = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Q", type="radio", options=["A", "B"], required=True),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="C", summary="s"),
            ),
            GraphNode(
                id="c2",
                type="conclusion",
                data=ConclusionData(title="D", summary="t"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="A"),
            GraphEdge(source="q1", target="c2", condition=None),
        ],
        metadata=QNRMetadata(title="default"),
    )
    ir2 = compile_qnr_to_ir(g2)
    assert ir2.guards[1].expr == DEFAULT_GUARD_EXPR
    assert validate_ir(ir2).valid


def test_validate_ir_duplicate_node_id():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="x", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="x", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(),
        guards=(),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("Duplicate node id" in e for e in r.errors)


def test_validate_ir_unknown_guard_on_edge():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="a", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="b", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="a", target="b", guard_id="g_missing"),),
        guards=(),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("unknown guard" in e for e in r.errors)


def test_validate_ir_unused_guard():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="a", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="b", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="a", target="b", guard_id="g_0"),),
        guards=(
            Guard(id="g_0", expr="A"),
            Guard(id="g_orphan", expr="orphan-unused"),
        ),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("Unused guard" in e for e in r.errors)


def test_validate_ir_edge_endpoint_missing():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(IRNode(id="a", kind=IRNodeKind.QUESTION, question=_Q_RADIO),),
        edges=(IREdge(source="a", target="ghost", guard_id="g_0"),),
        guards=(Guard(id="g_0", expr=DEFAULT_GUARD_EXPR),),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("target" in e.lower() for e in r.errors)


def test_validate_ir_duplicate_guard_id():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="a", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="b", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="a", target="b", guard_id="g_0"),),
        guards=(
            Guard(id="g_0", expr="A"),
            Guard(id="g_0", expr="B"),
        ),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("Duplicate guard id" in e for e in r.errors)


def test_validate_ir_bad_format_version():
    ir = IR(
        format_version=0,
        nodes=(IRNode(id="a", kind=IRNodeKind.CONCLUSION, question=None),),
        edges=(),
        guards=(),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("format_version" in e.lower() for e in r.errors)


def test_validate_ir_rejects_question_empty_options():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(
                id="Q1",
                kind=IRNodeKind.QUESTION,
                question=IRQuestionShape(qtype="radio", options=()),
            ),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="Q1", target="C1", guard_id="g_000000"),),
        guards=(Guard(id="g_000000", expr="A"),),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("non-empty options" in e for e in r.errors)


def test_validate_ir_rejects_non_radio_qtype():
    """Hand-built IR with invalid qtype string (artifact / fuzz) must fail validation."""
    bad_shape = IRQuestionShape(qtype="radio", options=("A", "B"))
    object.__setattr__(bad_shape, "qtype", "number")

    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=bad_shape),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="Q1", target="C1", guard_id="g_000000"),),
        guards=(Guard(id="g_000000", expr="A"),),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("qtype 'radio'" in e for e in r.errors)


def test_validate_ir_rejects_radio_expr_not_in_options():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="Q1", target="C1", guard_id="g_000000"),),
        guards=(Guard(id="g_000000", expr="Maybe"),),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("Radio guard expr not in question options" in e for e in r.errors)


def test_validate_ir_rejects_radio_whitespace_only_expr():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="Q1", target="C1", guard_id="g_000000"),),
        guards=(Guard(id="g_000000", expr="   \t  "),),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("Radio guard expr is empty or whitespace-only" in e for e in r.errors)


def test_validate_ir_rejects_self_loop():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="E1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="E1", target="Q1", guard_id="g_e"),
            IREdge(source="Q1", target="Q1", guard_id="g_0"),
            IREdge(source="Q1", target="C1", guard_id="g_1"),
        ),
        guards=(
            Guard(id="g_e", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_0", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_1", expr=DEFAULT_GUARD_EXPR),
        ),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("Self-loop" in e for e in r.errors)


def test_validate_ir_rejects_directed_cycle():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Q3", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
        ),
        edges=(
            IREdge(source="Q1", target="Q2", guard_id="g_0"),
            IREdge(source="Q2", target="Q3", guard_id="g_1"),
            IREdge(source="Q3", target="Q1", guard_id="g_2"),
        ),
        guards=(
            Guard(id="g_0", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_1", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_2", expr=DEFAULT_GUARD_EXPR),
        ),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("Directed cycle" in e for e in r.errors)


def test_validate_ir_rejects_disconnected_cycle_component():
    """Cycle off the entry component is still rejected (whole graph must be a DAG)."""
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="E1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="X1", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="Y1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Z1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
        ),
        edges=(
            IREdge(source="E1", target="X1", guard_id="g_e"),
            IREdge(source="Y1", target="Z1", guard_id="g_yz"),
            IREdge(source="Z1", target="Y1", guard_id="g_zy"),
        ),
        guards=(
            Guard(id="g_e", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_yz", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_zy", expr=DEFAULT_GUARD_EXPR),
        ),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("Directed cycle" in e for e in r.errors)


def test_validate_ir_accepts_dag_multiple_paths_to_same_conclusion():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q0", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Qa", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Qb", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q0", target="Qa", guard_id="g_0"),
            IREdge(source="Q0", target="Qb", guard_id="g_1"),
            IREdge(source="Qa", target="C1", guard_id="g_2"),
            IREdge(source="Qb", target="C1", guard_id="g_3"),
        ),
        guards=(
            Guard(id="g_0", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_1", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_2", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_3", expr=DEFAULT_GUARD_EXPR),
        ),
    )
    assert validate_ir(ir).valid


def test_validate_ir_accepts_dag_multiple_conclusions():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="C2", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q1", target="C1", guard_id="g_a"),
            IREdge(source="Q1", target="C2", guard_id="g_b"),
        ),
        guards=(
            Guard(id="g_a", expr="A"),
            Guard(id="g_b", expr="B"),
        ),
    )
    assert validate_ir(ir).valid


def test_validate_ir_rejects_multiple_entry_nodes():
    """Two disconnected roots → not valid for single-start QNR/session semantics."""
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
        ),
        edges=(),
        guards=(),
    )
    r = validate_ir(ir)
    assert not r.valid
    assert any("exactly one entry" in e.lower() for e in r.errors)
