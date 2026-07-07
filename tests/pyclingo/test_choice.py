"""
Tests for Choice construction guards.
"""

import pytest

from pyclingo import ASPProgram, Choice, Count, Not, Number, Predicate, Variable


def test_impossible_cardinality_rejected() -> None:
    # Statically impossible bounds would render fine but be silently UNSAT
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match="impossible"):
        Choice(P(x=1)).at_least(3).at_most(2)
    with pytest.raises(ValueError, match="impossible"):
        Choice(P(x=1)).at_most(2).at_least(3)
    Choice(P(x=1)).at_least(2).at_most(3)  # possible bounds fine
    Choice(P(x=1)).at_least(Variable("N")).at_most(2)  # variable bounds skipped


def test_aggregates_rejected_in_conditions() -> None:
    # clingo cannot parse an aggregate inside a choice condition
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="inside choice conditions"):
        Choice(P(x=X), condition=Count(Y, condition=P(x=Y)) > 0)
    with pytest.raises(ValueError, match="inside choice conditions"):
        Choice(P(x=X), condition=[P(x=X), Count(Y, condition=P(x=Y)) > 0])


def test_aggregates_on_both_comparison_sides_rejected() -> None:
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="both sides"):
        _ = Count(X, condition=P(x=X)) == Count(Y, condition=P(x=Y))


def test_choice_freezes_when_captured_by_a_rule() -> None:
    program = ASPProgram()
    P, Q = Predicate.define("p", ["x"]), Predicate.define("q", ["x"])
    X = Variable("X")
    choice = Choice(P(x=X), condition=Q(x=X))
    program.when(Q(x=X), let=choice)
    with pytest.raises(RuntimeError, match="frozen"):
        choice.add(P(x=X))
    with pytest.raises(RuntimeError, match="frozen"):
        choice.at_most(3)


def test_choice_builds_freely_before_capture_and_shares_after() -> None:
    program = ASPProgram()
    P, Q, R = (Predicate.define(n, ["x"]) for n in ("p", "q", "r"))
    X = Variable("X")
    choice = Choice(P(x=X), condition=Q(x=X)).add(R(x=X)).exactly(1)  # chaining pre-capture
    program.when(Q(x=X), let=choice)
    program.when(R(x=X), let=choice)  # sharing a built choice is fine
    assert program.render().count("{ p(X) : q(X); r(X) } = 1") == 2


def test_negative_cardinality_rejected_for_number_too() -> None:
    # The int path and the Number path validate identically
    P = Predicate.define("p9", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match="non-negative"):
        Choice(P(x=X)).exactly(-1)
    with pytest.raises(ValueError, match="non-negative"):
        Choice(P(x=X)).exactly(Number(-1))


def test_negation_wrapped_aggregate_condition_rejected() -> None:
    # Not(...) wrapping must not smuggle an aggregate past the guard
    P = Predicate.define("p10", ["x"])
    Q = Predicate.define("q10", ["x"])
    X, C = Variable("X"), Variable("C")
    with pytest.raises(ValueError, match="separate rule"):
        Choice(P(x=X), condition=Not(Count(C, condition=Q(x=C)) > 3))


def test_expression_cardinality_bounds() -> None:
    # { pick(X) : c(X) } = N + 1 :- size(N).  — gringo-legal, probed
    program = ASPProgram()
    Size = Predicate.define("size", ["n"], show=False)
    C = Predicate.define("c", ["x"], show=False)
    Pick = Predicate.define("pick", ["x"])
    N, X = Variable("N"), Variable("X")
    program.fact(Size(n=2), *[C(x=i) for i in range(1, 5)])
    program.when(Size(n=N), let=Choice(Pick(x=X), condition=C(x=X)).exactly(N + 1))
    models = list(program.solve())
    assert len(models) == 4  # C(4, 3) ways to pick 3 of 4
    assert all(len(m.atoms(Pick)) == 3 for m in models)


def test_expression_bound_variables_must_bind() -> None:
    # The bound's variables are global: unbound ones are rejected
    program = ASPProgram()
    P = Predicate.define("p_eb", ["x"])
    Q = Predicate.define("q_eb", ["x"])
    N, X = Variable("N"), Variable("X")
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.when(Q(x=1), let=Choice(P(x=X), condition=Q(x=X)).exactly(N + 1))
