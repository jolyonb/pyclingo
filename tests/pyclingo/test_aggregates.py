"""
Tests for Aggregate construction guards.
"""

import inspect
import re

import pytest

from pyclingo import ASPProgram, Count, Number, Predicate, SourceLocation, Sum, Variable


def test_aggregates_rejected_in_aggregate_conditions() -> None:
    # clingo cannot parse a nested aggregate; compute it in a separate rule
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="inside aggregate conditions"):
        Count(X, condition=[P(x=X), Count(Y, condition=P(x=Y)) > 0])


def test_aggregate_freezes_when_captured_inside_a_comparison() -> None:
    program = ASPProgram()
    P, Q = Predicate.define("p", ["x"]), Predicate.define("q", ["x"])
    X, Y = Variable("X"), Variable("Y")
    count = Count(X, condition=P(x=X))
    program.when(count == 2).derive(Q(x=1))  # aggregate reaches the rule via the Comparison
    with pytest.raises(RuntimeError, match="frozen"):
        count.add(Y, P(x=Y))


def test_frozen_aggregate_error_names_the_capturing_line() -> None:
    # The capture is transitive — the rule freezes the comparison, which
    # freezes the aggregate — and the receipt still lands on the user's line
    program = ASPProgram()
    P, Q = Predicate.define("p_rc", ["x"]), Predicate.define("q_rc", ["x"])
    X, Y = Variable("X"), Variable("Y")
    count = Count(X, condition=P(x=X))
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    program.when(count == 2).derive(Q(x=1))  # lineno + 1
    where = SourceLocation(frame.f_code.co_filename, lineno + 1).display()
    with pytest.raises(RuntimeError, match=re.escape(f"captured by the rule at {where}")):
        count.add(Y, P(x=Y))


def test_frozen_aggregate_is_a_value_shared_across_rules() -> None:
    # Build once, use many: the same comparison (and its aggregate) under
    # two different bodies renders in both rules
    program = ASPProgram()
    P = Predicate.define("p_sv", ["x"])
    A, B = Predicate.define("a_sv", []), Predicate.define("b_sv", [])
    X = Variable("X")
    too_many = Count(X, condition=P(x=X)) > 3
    program.when(A()).require(too_many)
    program.when(B()).require(too_many)
    assert program.render().count("#count{ X : p_sv(X) }") == 2


def test_expression_weights_solve() -> None:
    # #sum{ X * 2, X : p(X) } over p(1..3) = 12 (probed against gringo)
    P = Predicate.define("p6", ["x"], show=False)
    T = Predicate.define("t6", ["s"])
    S, X = Variable("S"), Variable("X")
    program = ASPProgram()
    program.fact(*[P(x=i) for i in (1, 2, 3)])
    program.when(S == Sum((X * 2, X), condition=P(x=X))).derive(T(s=S))
    model = next(iter(program.solve()))
    assert [atom["s"].value for atom in model.atoms(T)] == [12]


def test_expression_element_renders() -> None:
    X = Variable("X")
    P = Predicate.define("p7", ["x"])
    assert Sum((X * 2, X), condition=P(x=X)).render() == "#sum{ X * 2, X : p7(X) }"


def test_expression_element_variables_are_scoped() -> None:
    # The expression's variables are aggregate locals: unbound ones are
    # rejected with the local-safety error, not silently accepted
    P = Predicate.define("p8", ["x"])
    Q = Predicate.define("q8", ["x"])
    S, X, Y = Variable("S"), Variable("X"), Variable("Y")
    program = ASPProgram()
    with pytest.raises(ValueError, match="Unsafe local"):
        program.when(S == Sum((X * Y, X), condition=P(x=X))).derive(Q(x=S))


def test_aggregate_element_rejects_raw_python_value() -> None:
    # A bare int is neither Value, Expression, nor Predicate
    with pytest.raises(TypeError, match="Values, Expressions, or Predicates"):
        Count(5)  # type: ignore[arg-type]


def test_aggregate_tuple_element_rejects_bad_item() -> None:
    # The tuple path checks each item; the raw int trips the guard
    X = Variable("X")
    with pytest.raises(TypeError, match="Values, Expressions, or Predicates"):
        Sum((1, X))  # type: ignore[arg-type]


def test_aggregate_is_grounded_reflects_elements() -> None:
    assert Count(Variable("X")).is_grounded is False
    assert Count(Number(3)).is_grounded is True


def test_aggregate_str_delegates_to_render() -> None:
    X = Variable("X")
    assert str(Count(X)) == "#count{ X }"


def test_aggregate_repr_wraps_render() -> None:
    X = Variable("X")
    assert repr(Count(X)) == "Count('#count{ X }')"


def test_aggregate_validate_in_context_always_raises() -> None:
    X = Variable("X")
    with pytest.raises(ValueError, match="must be used in comparisons"):
        Count(X).validate_in_context(is_in_head=True)


def test_aggregate_collect_variables_spans_elements_and_conditions() -> None:
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    assert Count(X, condition=P(x=Y)).collect_variables() == {"X", "Y"}
