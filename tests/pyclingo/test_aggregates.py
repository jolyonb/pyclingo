"""
Tests for Aggregate construction guards.
"""

import pytest

from pyclingo import ASPProgram, Count, Predicate, Sum, Variable


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
