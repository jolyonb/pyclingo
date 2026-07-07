"""
Tests for require(): forbid stated positively. require(C, when=W) renders a
constraint on the inverse comparison — it checks, it never derives.
"""

import pytest

from pyclingo import ASPProgram, Count, Predicate, Variable

X = Variable("X")


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
    program.require(Count(C, condition=P(x=C)) == N, when=Clue(num=N))
    assert ":- clue(N), #count{ C : p(C) } != N." in program.render()


def test_require_solves_correctly() -> None:
    # clue(2) with p(1), p(2): count == 2 holds -> SAT; clue(3) -> UNSAT
    def build(clue: int) -> ASPProgram:
        program = ASPProgram()
        Clue = Predicate.define("clue2", ["num"], show=False)
        P = Predicate.define("p2", ["x"], show=False)
        N, C = Variable("N"), Variable("C")
        program.fact(Clue(num=clue), P(x=1), P(x=2))
        program.require(Count(C, condition=P(x=C)) == N, when=Clue(num=N))
        return program

    assert next(iter(build(2).solve()), None) is not None
    result = build(3).solve()
    assert list(result) == []
    assert result.satisfiable is False


def test_require_without_when() -> None:
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
    with pytest.raises(TypeError, match="derive it with when"):
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
