"""
Tests for the ~ operator and Not(): default negation on predicates and
comparisons, ground-truthed by solving (render-only pins let invalid ASP
ship once; see AUDIT_v2 H1).
"""

import pytest

from pyclingo import ASPProgram, Not, Predicate, Variable


def test_invert_on_predicates() -> None:
    P = Predicate.define("p", ["x"])
    assert (~P(x=1)).render() == "not p(1)"


def test_invert_on_comparisons() -> None:
    # No parentheses: clingo rejects "not (X < 5)"
    X = Variable("X")
    assert (~(X < 5)).render() == "not X < 5"
    assert (~(X == 5)).render() == "not X = 5"


def test_invert_nests_and_simplifies_like_not() -> None:
    X = Variable("X")
    assert (~~(X < 5)).render() == "not not X < 5"
    assert (~~~(X < 5)).render() == "not X < 5"  # triple simplifies
    assert (~(X < 5)).render() == Not(X < 5).render()


def test_negated_comparison_solves_correctly() -> None:
    # Ground truth: p(1..5) with not X < 3 must yield q(3), q(4), q(5)
    program = ASPProgram()
    P = Predicate.define("p", ["x"], show=False)
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    program.fact(*[P(x=i) for i in range(1, 6)])
    program.when(P(x=X), Not(X < 3)).derive(Q(x=X))
    model = next(iter(program.solve()))
    assert sorted(atom["x"].value for atom in model.atoms(Q)) == [3, 4, 5]


def test_double_negated_comparison_solves() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"], show=False)
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    program.fact(*[P(x=i) for i in range(1, 4)])
    program.when(P(x=X), Not(Not(X == 2))).derive(Q(x=X))
    model = next(iter(program.solve()))
    assert [atom["x"].value for atom in model.atoms(Q)] == [2]


def test_negated_pool_comparison_rejected() -> None:
    # "not X = (2;3)" parses but expands disjunctively — true for every X
    X = Variable("X")
    with pytest.raises(ValueError, match="disjunctively"):
        Not(X.in_([2, 3]))
    with pytest.raises(ValueError, match="disjunctively"):
        _ = ~X.in_([2, 3])
