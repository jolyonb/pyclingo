"""
Tests for the ~ operator and Not(): default negation on predicates, the
NORMALIZATION of plain comparisons to their complements, and the
aggregate carve-out that keeps the "not" wrapper. Semantics are asserted
by solving where possible; the binding behavior of normalized
comparisons additionally carries live gringo receipts in
test_scoping.py. The whole design is documented on Not() and in
aspalchemy/CLAUDE.md.
"""

import pytest

from aspalchemy import ASPProgram, Comparison, Count, Not, Number, Predicate, Variable
from aspalchemy.core import DefaultNegation


def test_invert_on_predicates() -> None:
    P = Predicate.define("p", ["x"])
    assert (~P(x=1)).render() == "not p(1)"


def test_atom_double_negation_is_preserved_and_triple_collapses() -> None:
    # Stable-model semantics: "not not p" is NOT p (p may support itself
    # through it), while "not not not p" IS "not p" — so doubles must
    # survive and triples must fold (Lifschitz, ASP, ch. 5)
    P = Predicate.define("p", ["x"])
    assert (~~P(x=1)).render() == "not not p(1)"
    assert (~~~P(x=1)).render() == "not p(1)"


def test_plain_comparisons_normalize_to_their_complements() -> None:
    # gringo normalizes "not CMP" to the complementary comparison before
    # evaluating; Not()/~ perform the same normalization at construction,
    # so the result is visible and safe to bind through
    X = Variable("X")
    for negated, expected in [
        (Not(X < 5), "X >= 5"),
        (Not(X <= 5), "X > 5"),
        (Not(X > 5), "X <= 5"),
        (Not(X >= 5), "X < 5"),
        (Not(X == 5), "X != 5"),
        (Not(X != 5), "X = 5"),
    ]:
        assert isinstance(negated, Comparison)
        assert negated.render() == expected
    assert (~(X < 5)).render() == "X >= 5"  # ~ is Not


def test_double_negation_over_comparisons_composes_to_identity() -> None:
    # Unlike atoms, comparisons have no foundedness to protect: the inner
    # Not inverts, the outer inverts back — Not(Not(cmp)) IS cmp
    X = Variable("X")
    assert (~~(X < 5)).render() == "X < 5"
    assert (~~~(X < 5)).render() == "X >= 5"
    assert Not(Not(X != 5)).render() == "X != 5"


def test_aggregate_comparisons_keep_the_not_wrapper() -> None:
    # A negated aggregate literal is not complement-flippable under
    # stable-model semantics: the wrapper is the safe spelling, doubles
    # preserved exactly as for atoms
    P = Predicate.define("p", ["x"])
    X = Variable("X")
    aggregate_comparison = Count(X, condition=P(x=X)) > 3
    assert Not(aggregate_comparison).render() == "not #count{ X : p(X) } > 3"
    assert Not(Not(aggregate_comparison)).render() == "not not #count{ X : p(X) } > 3"


def test_default_negation_refuses_plain_comparisons() -> None:
    # One behavior, one door: a hand-built wrapper would render "not X = 5"
    # while meaning "X != 5" — the constructor teaches the normalizing doors
    X = Variable("X")
    with pytest.raises(ValueError, match=r"never wraps in 'not'.*complement"):
        DefaultNegation(X == 5)


def test_negated_comparison_solves_correctly() -> None:
    # Ground truth: p(1..5) with Not(X < 3) — now the complement X >= 3 —
    # must yield q(3), q(4), q(5)
    program = ASPProgram()
    P = Predicate.define("p", ["x"], show=False)
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    program.fact(*[P(x=i) for i in range(1, 6)])
    program.when(P(x=X), Not(X < 3)).derive(Q(x=X))
    model = program.solve().first()
    assert sorted(atom["x"].value for atom in model.atoms(Q)) == [3, 4, 5]


def test_normalized_negation_binds_like_gringo() -> None:
    # THE case the normalization exists for: Not(X != Y) is the binding
    # equality X = Y, so X is safe — exactly gringo's own reading of
    # "not X != Y" (live receipt: test_scoping's
    # test_negated_inequality_normalizes_to_binding_equality)
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"], show=False)
    X, Y = Variable("X"), Variable("Y")
    program.fact(Q(x=1), Q(x=2))
    program.when(Q(x=Y), Not(X != Y)).derive(P(x=X))
    model = program.solve().first()
    assert sorted(atom["x"].value for atom in model.atoms(P)) == [1, 2]


def test_double_negated_comparison_solves() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"], show=False)
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    program.fact(*[P(x=i) for i in range(1, 4)])
    program.when(P(x=X), Not(Not(X == 2))).derive(Q(x=X))
    model = program.solve().first()
    assert [atom["x"].value for atom in model.atoms(Q)] == [2]


def test_negated_pool_comparison_rejected() -> None:
    # "not X = (2;3)" parses but expands disjunctively — true for every X
    X = Variable("X")
    with pytest.raises(ValueError, match="disjunctively"):
        Not(X.in_([2, 3]))
    with pytest.raises(ValueError, match="disjunctively"):
        _ = ~X.in_([2, 3])


def test_not_on_non_negatable_rejected() -> None:
    # A bare Value (Number) is not Negatable: predicates and comparisons are.
    with pytest.raises(TypeError, match="predicates, comparisons"):
        Not(Number(5))  # type: ignore[arg-type]
