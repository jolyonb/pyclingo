"""
Tests for predicates as comparison operands: X == Cell(1, 2) binds,
C == Cell(X, ANY) destructures, C != Cell(1, 1) excludes. A Variable must
be on the other side — clingo orders terms by type, so comparing a number
or expression against a compound term is vacuous.
"""

import pytest

from pyclingo import ANY, ASPProgram, Predicate, Variable

Cell = Predicate.define("cell", ["row", "col"], show=False)
Holds = Predicate.define("holds", ["c"], show=False)


def test_render_forms() -> None:
    X = Variable("X")
    assert (X == Cell(row=1, col=2)).render() == "X = cell(1, 2)"
    assert (X != Cell(row=1, col=2)).render() == "X != cell(1, 2)"
    assert (X < Cell(row=2, col=2)).render() == "X < cell(2, 2)"
    # Ungrounded compounds are fine: this is the destructuring shape
    R = Variable("R")
    assert (X == Cell(row=R, col=ANY)).render() == "X = cell(R, _)"


def test_construction_binds() -> None:
    # C = cell(X, Y) with X, Y bound binds C (probed against gringo)
    P = Predicate.define("p", ["x"], show=False)
    Q = Predicate.define("q", ["c"])
    C, X, Y = Variable("C"), Variable("X"), Variable("Y")
    program = ASPProgram()
    program.fact(P(x=1), P(x=2))
    program.when(P(x=X), P(x=Y), X < Y, C == Cell(row=X, col=Y), let=Q(c=C))
    model = next(iter(program.solve()))
    assert [str(atom["c"]) for atom in model.atoms(Q)] == ["cell(1, 2)"]


def test_destructuring_binds() -> None:
    # With C bound, C = cell(X, _) extracts X (probed against gringo)
    R = Predicate.define("r", ["x"])
    C, X = Variable("C"), Variable("X")
    program = ASPProgram()
    program.fact(Holds(c=Cell(row=3, col=4)))
    program.when(Holds(c=C), C == Cell(row=X, col=ANY), let=R(x=X))
    model = next(iter(program.solve()))
    assert [atom["x"].value for atom in model.atoms(R)] == [3]


def test_not_equal_excludes() -> None:
    T = Predicate.define("t", ["c"])
    C = Variable("C")
    program = ASPProgram()
    program.fact(Holds(c=Cell(row=1, col=1)), Holds(c=Cell(row=1, col=2)))
    program.when(Holds(c=C), C != Cell(row=1, col=1), let=T(c=C))
    model = next(iter(program.solve()))
    assert [str(atom["c"]) for atom in model.atoms(T)] == ["cell(1, 2)"]


def test_compound_operand_requires_a_variable() -> None:
    # Number-vs-compound and expression-vs-compound are vacuous by type order
    X = Variable("X")
    with pytest.raises(ValueError, match="Variable on the other side"):
        _ = (X + 1) == Cell(row=1, col=2)
    with pytest.raises(ValueError, match="Variable on the other side"):
        _ = (X + 1) < Cell(row=1, col=2)


def test_comparison_operand_has_no_show_signature() -> None:
    # cell appears only as a comparison operand: a term, not an atom — no
    # "#show cell/2." may be emitted (it would draw a gringo info)
    Q = Predicate.define("q2", ["c"])
    C = Variable("C")
    program = ASPProgram()
    program.fact(Holds(c=Cell(row=1, col=1)))
    program.when(Holds(c=C), C != Cell(row=9, col=9), let=Q(c=C))
    rendered = program.render()
    assert "#show cell/2." not in rendered
    assert "#show q2/1." in rendered
