"""
Tests for classical (strong) negation: -p(...) asserts an atom is false.
The sign is part of the atom — a negated Predicate is still a Predicate.
"""

import pytest

from pyclingo import ASPProgram, Choice, Field, Not, Predicate, Variable

P = Predicate.define("p", ["x"])
Q = Predicate.define("q", ["x"])


def test_the_three_representations_carry_the_sign() -> None:
    atom = -P(x=1)
    assert atom.render() == "-p(1)"
    assert atom.canonical_str() == "-p(x=1)"
    assert repr(atom) == "-p(x=Number(1))"


def test_double_negation_is_identity() -> None:
    atom = P(x=1)
    negation = -atom
    assert -negation == atom
    assert not (-negation).negated


def test_signs_distinguish_atoms() -> None:
    assert -P(x=1) != P(x=1)
    assert -P(x=1) == -P(x=1)
    assert len({P(x=1), -P(x=1)}) == 2


def test_default_negation_composes() -> None:
    X = Variable("X")
    assert Not(-P(x=X)).render() == "not -p(X)"
    assert (~-P(x=X)).render() == "not -p(X)"


def test_negated_atoms_bind_in_bodies() -> None:
    # -r(X) is a positive occurrence of an atom: it binds (probed)
    program = ASPProgram()
    program.fact(-P(x=2))
    X = Variable("X")
    program.when(-P(x=X), let=Q(x=X))
    model = next(iter(program.solve()))
    assert [a["x"].value for a in model.atoms(Q)] == [2]
    negatives = [a for a in model.atoms(P) if a.negated]
    assert [a["x"].value for a in negatives] == [2]


def test_atoms_returns_both_signs() -> None:
    # A negated predicate is just a predicate: atoms(P) holds both signs,
    # and .negated is the caller's filter
    program = ASPProgram()
    program.fact(P(x=1), -P(x=2))
    model = next(iter(program.solve()))
    by_sign = {a.negated: a["x"].value for a in model.atoms(P)}
    assert by_sign == {False: 1, True: 2}
    assert len(model.atoms()) == 2


def test_show_directive_emitted_only_when_negated_atoms_exist() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    assert "#show -p/1." not in program.render()

    negative_program = ASPProgram()
    negative_program.fact(P(x=1), -P(x=2))
    rendered = negative_program.render()
    assert "#show p/1." in rendered
    assert "#show -p/1." in rendered


def test_contradiction_is_unsat() -> None:
    program = ASPProgram()
    program.fact(P(x=1), -P(x=1))
    result = program.solve()
    assert list(result) == []
    assert result.satisfiable is False


def test_signed_atoms_nest_as_arguments() -> None:
    Holds = Predicate.define("holds", ["what"])
    program = ASPProgram()
    program.fact(Holds(what=-P(x=1)))
    model = next(iter(program.solve()))
    inner = model.atoms(Holds)[0]["what"]
    assert inner.negated and inner == -P(x=1)


def test_typed_slots_accept_signed_atoms() -> None:
    # A negated predicate is just a predicate: Field[P] takes both signs
    class Wrap(Predicate, show=False):
        inner: Field[P]  # type: ignore[valid-type]

    assert Wrap(inner=-P(x=1)).render() == "wrap(-p(1))"


def test_choice_over_negated_atoms() -> None:
    X = Variable("X")
    choice = Choice(-P(x=X), condition=Q(x=X))
    assert choice.render() == "{ -p(X) : q(X) }"


def test_scoping_counts_signed_atoms() -> None:
    # A negated atom's variables participate in safety and singleton checks
    program = ASPProgram()
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="Singleton"):
        program.when(-P(x=X), let=Q(x=X), segment="a")
        program.when(P(x=X), -Q(x=Y), let=Q(x=X))
