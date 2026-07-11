"""
Tests for solution reconstruction: model symbols back into typed Predicates.
"""

import inspect
import re

import pytest

from aspalchemy import ASPProgram, Predicate, SourceLocation


def test_arity_overloads_reconstruct_as_their_own_classes() -> None:
    # p/1 and p/2 are distinct predicates in ASP; reconstruction is keyed by
    # (name, arity)
    program = ASPProgram()
    Edge2 = Predicate.define("edge", ["a", "b"])
    Edge3 = Predicate.define("edge", ["a", "b", "w"])
    program.fact(Edge2(a=1, b=2), Edge3(a=1, b=2, w=9))
    model = next(iter(program.solve()))
    assert model.atoms(Edge2) == [Edge2(a=1, b=2)]
    assert model.atoms(Edge3) == [Edge3(a=1, b=2, w=9)]


def test_same_signature_collision_raises_at_render() -> None:
    program = ASPProgram()
    A = Predicate.define("cell", ["x"])
    B = Predicate.define("cell", ["y"])
    program.fact(A(x=1), B(y=2))
    with pytest.raises(ValueError, match="Predicate name collision: 'cell/1'"):
        program.render()


def test_collision_error_names_both_definition_sites() -> None:
    # The colliding classes' names match by definition, so the error
    # disambiguates by where each was defined
    program = ASPProgram()
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    A = Predicate.define("clash", ["x"])  # lineno + 1
    B = Predicate.define("clash", ["y"])  # lineno + 2
    program.fact(A(x=1), B(y=2))
    first = SourceLocation(frame.f_code.co_filename, lineno + 1).display()
    second = SourceLocation(frame.f_code.co_filename, lineno + 2).display()
    with pytest.raises(ValueError, match=re.escape(f"defined at {first}")) as excinfo:
        program.render()
    assert f"defined at {second}" in str(excinfo.value)


def test_bare_atoms_reconstruct_as_nullary_predicates() -> None:
    # Unregistered bare atoms fail loudly as unknown predicates instead
    program = ASPProgram()
    N = Predicate.define("flag", [], show=False)  # argument-only: no flag/0 atoms to show
    Holds = Predicate.define("holds", ["what"])
    program.fact(Holds(what=N()))
    model = next(iter(program.solve()))
    assert isinstance(model.atoms(Holds)[0]["what"], N)


def test_deeply_nested_predicates_reconstruct_the_class_tree() -> None:
    # A predicate nested two levels deep must rebuild the whole class tree on
    # readback, not flatten or stringify: holds(pair(1, pair(2, 3)))
    Pair = Predicate.define("pair", ["a", "b"])
    Holds = Predicate.define("holds_nested", ["what"])
    program = ASPProgram()
    program.fact(Holds(what=Pair(a=1, b=Pair(a=2, b=3))))
    what = next(iter(program.solve())).atoms(Holds)[0]["what"]
    assert isinstance(what, Pair) and what["a"].value == 1
    inner = what["b"]  # the second Pair, reconstructed as its own class
    assert isinstance(inner, Pair)
    assert (inner["a"].value, inner["b"].value) == (2, 3)
