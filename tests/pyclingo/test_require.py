"""
Tests for require(): forbid stated positively. require(C) — flat or as a
when() closer — renders a constraint on the inverse comparison (the
implication conditions -> C); it checks, it never derives. Inversion is
semantic negation only for BOUND comparisons; the probe tests below pin
that equivalence against clingo's own evaluation, and the safety pin
holds the boundness precondition.
"""

from collections.abc import Callable
from typing import Any

import pytest

from pyclingo import ASPProgram, Choice, Count, Predicate, RangePool, Variable

X = Variable("X")

# One lambda per operator serves both sides of the probe: applied to ints it
# is the Python ground truth, applied to Variables it builds the Comparison
COMPARISON_BUILDERS: list[tuple[str, Callable[[Any, Any], Any]]] = [
    ("eq", lambda a, b: a == b),
    ("ne", lambda a, b: a != b),
    ("lt", lambda a, b: a < b),
    ("le", lambda a, b: a <= b),
    ("gt", lambda a, b: a > b),
    ("ge", lambda a, b: a >= b),
]


@pytest.mark.parametrize(("op_name", "op"), COMPARISON_BUILDERS, ids=[name for name, _ in COMPARISON_BUILDERS])
def test_require_keeps_exactly_the_pairs_where_the_comparison_holds(
    op_name: str, op: Callable[[Any, Any], Any]
) -> None:
    # Probe-derived: under a pick-one choice over all (x, y) pairs,
    # require(X op Y) must keep exactly the pairs where Python agrees the
    # comparison holds — inversion is semantic negation, per clingo itself
    domain = range(1, 4)
    V = Predicate.define(f"v_{op_name}", ["n"], show=False)
    Pick = Predicate.define(f"pick_{op_name}", ["x", "y"])
    A, B = Variable("A"), Variable("B")
    program = ASPProgram()
    program.fact(*[V(n=k) for k in domain])
    program.fact(Choice(Pick(x=A, y=B), condition=[V(n=A), V(n=B)]).exactly(1))
    program.when(Pick(x=A, y=B)).require(op(A, B))
    kept = {(pick["x"].value, pick["y"].value) for model in program.solve() for pick in model.atoms(Pick)}
    assert kept == {(a, b) for a in domain for b in domain if op(a, b)}


def test_require_inversion_composes_with_negated_body_literals() -> None:
    # The inverse rides in a body alongside default negation: the constraint
    # kills exactly the models where the negation HOLDS and the comparison
    # fails — a flagged pick survives regardless of the comparison
    program = ASPProgram()
    V = Predicate.define("v_neg", ["n"], show=False)
    Flag = Predicate.define("flag_neg", ["x"], show=False)
    Pick = Predicate.define("pick_neg", ["x"])
    program.fact(*[V(n=k) for k in range(1, 5)])
    program.fact(Flag(x=2), Flag(x=4))
    program.fact(Choice(Pick(x=X), condition=V(n=X)).exactly(1))
    program.when(Pick(x=X), ~Flag(x=X)).require(X < 3)
    assert ":- pick_neg(X), not flag_neg(X), X >= 3." in program.render()
    kept = {model.atoms(Pick)[0]["x"].value for model in program.solve()}
    assert kept == {1, 2, 4}  # 1 satisfies X < 3; 2 and 4 escape via the flag; 3 is killed


def test_require_rejects_variables_the_inverse_cannot_bind() -> None:
    # Negative literals do not bind, and neither does the inverse X >= 3:
    # inversion is only semantic negation for bound comparisons, and the
    # safety analysis holds that precondition at the closer
    program = ASPProgram()
    Q = Predicate.define("q_unbound", ["x"])
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.when(~Q(x=X)).require(X < 3)


def test_require_inequality_is_safe_because_its_inverse_binds() -> None:
    # The subtle corner: require(X != 3) under a purely negative body is
    # SAFE — the inverse is X = 3, and equality with a constant binds in
    # gringo. Semantics probe: "not q(X) -> X != 3" at X = 3 forces q(3),
    # and the model count shows nothing else was constrained.
    program = ASPProgram()
    Q = Predicate.define("q_eq_binds", ["x"])
    program.fact(Choice(Q(x=RangePool(1, 4))))  # free choice over q(1..4)
    program.when(~Q(x=X)).require(X != 3)
    assert ":- not q_eq_binds(X), X = 3." in program.render()
    models = [frozenset(atom["x"].value for atom in model.atoms(Q)) for model in program.solve()]
    assert all(3 in model for model in models)
    assert len(models) == 8  # 2^3: q(1), q(2), q(4) stay free


def test_inverse_covers_all_operators() -> None:
    pairs = [
        (X == 3, "X != 3"),
        (X != 3, "X = 3"),
        (X < 3, "X >= 3"),
        (X >= 3, "X < 3"),
        (X > 3, "X <= 3"),
        (X <= 3, "X > 3"),
    ]
    for comparison, expected in pairs:
        assert comparison.inverse().render() == expected
        # Inverting twice returns to the original
        assert comparison.inverse().inverse().render() == comparison.render()


def test_require_renders_the_inverse_constraint() -> None:
    # The minesweeper shape: exactly N matching neighbours
    program = ASPProgram()
    Clue = Predicate.define("clue", ["num"], show=False)
    P = Predicate.define("p", ["x"], show=False)
    N, C = Variable("N"), Variable("C")
    program.fact(Clue(num=1), P(x=1))
    program.when(Clue(num=N)).require(Count(C, condition=P(x=C)) == N)
    assert ":- clue(N), #count{ C : p(C) } != N." in program.render()


def test_require_solves_correctly() -> None:
    # clue(2) with p(1), p(2): count == 2 holds -> SAT; clue(3) -> UNSAT
    def build(clue: int) -> ASPProgram:
        program = ASPProgram()
        Clue = Predicate.define("clue2", ["num"], show=False)
        P = Predicate.define("p2", ["x"], show=False)
        N, C = Variable("N"), Variable("C")
        program.fact(Clue(num=clue), P(x=1), P(x=2))
        program.when(Clue(num=N)).require(Count(C, condition=P(x=C)) == N)
        return program

    assert next(iter(build(2).solve()), None) is not None
    result = build(3).solve()
    assert list(result) == []
    assert result.satisfiable is False


def test_require_without_conditions() -> None:
    # A global requirement: at least 2 atoms chosen
    program = ASPProgram()
    P = Predicate.define("p3", ["x"], show=False)
    C = Variable("C")
    program.fact(P(x=1), P(x=2), P(x=3))
    program.require(Count(C, condition=P(x=C)) >= 2)
    assert ":- #count{ C : p3(C) } < 2." in program.render()


def test_require_rejects_predicates_with_teaching() -> None:
    program = ASPProgram()
    P = Predicate.define("p4", ["x"])
    with pytest.raises(TypeError, match=r"derive it: when\(\*conditions\)\.derive"):
        program.require(P(x=1))  # type: ignore[arg-type]


def test_require_rejects_pool_comparisons() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="disjunctively"):
        program.require(X.in_([2, 3]))


def test_require_checks_rather_than_derives() -> None:
    # require on a comparison whose truth depends on derived atoms: the
    # UNSAT outcome proves it checked instead of deriving anything
    program = ASPProgram()
    P = Predicate.define("p5", ["x"], show=False)
    C = Variable("C")
    program.fact(P(x=1))
    program.require(Count(C, condition=P(x=C)) == 5)
    result = program.solve()
    assert list(result) == []
    assert result.satisfiable is False


def test_require_rejects_extra_arguments_with_teaching() -> None:
    # require() takes one comparison; conditions belong in when()
    program = ASPProgram()
    P = Predicate.define("p11", ["x"])
    C = Variable("C")
    with pytest.raises(TypeError, match=r"exactly one Comparison; conditions go in when\(\)"):
        program.require(P(x=C), C > 0)


def test_inverse_refuses_pool_comparisons_with_explanation() -> None:
    with pytest.raises(ValueError, match="disjunctively"):
        X.in_([2, 3]).inverse()
