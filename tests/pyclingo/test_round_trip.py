"""
Tests for solution reconstruction: model symbols back into typed Predicates.
"""

import pytest

from pyclingo import ASPProgram, Predicate


def test_arity_overloads_reconstruct_as_their_own_classes() -> None:
    # p/1 and p/2 are distinct predicates in ASP; reconstruction is keyed by
    # (name, arity)
    program = ASPProgram()
    Edge2 = Predicate.define("edge", ["a", "b"])
    Edge3 = Predicate.define("edge", ["a", "b", "w"])
    program.fact(Edge2(a=1, b=2), Edge3(a=1, b=2, w=9))
    solution = list(program.solve())[0]
    assert {type(i) for i in solution["edge"]} == {Edge2, Edge3}


def test_same_signature_collision_raises_at_render() -> None:
    program = ASPProgram()
    A = Predicate.define("cell", ["x"])
    B = Predicate.define("cell", ["y"])
    program.fact(A(x=1), B(y=2))
    with pytest.raises(ValueError, match="Predicate name collision: 'cell/1'"):
        program.render()


def test_bare_atoms_reconstruct_as_nullary_predicates() -> None:
    # Unregistered bare atoms fail loudly as unknown predicates instead
    program = ASPProgram()
    N = Predicate.define("flag", [], show=False)  # argument-only: no flag/0 atoms to show
    Holds = Predicate.define("holds", ["what"])
    program.fact(Holds(what=N()))
    solution = list(program.solve())[0]
    assert isinstance(solution["holds"][0]["what"], N)
