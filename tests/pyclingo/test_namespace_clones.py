"""
Tests for in_namespace(): cached namespaced copies of predicate classes.
"""

import pytest

from pyclingo import ASPProgram, Field, Predicate


class Clue(Predicate):
    loc: Field[str]
    value: Field[int]


def test_clone_renders_under_the_namespace() -> None:
    GridClue = Clue.in_namespace("grid")
    assert GridClue.get_name() == "grid_clue"
    assert GridClue(loc="a1", value=7).render() == 'grid_clue("a1", 7)'


def test_clones_are_cached_and_identity_stable() -> None:
    assert Clue.in_namespace("grid") is Clue.in_namespace("grid")
    assert Clue.in_namespace("") is Clue  # same-namespace fast path


def test_typed_fields_are_inherited() -> None:
    GridClue = Clue.in_namespace("grid")
    clue = GridClue(loc="a1", value=7)
    assert clue.value == 7 and isinstance(clue.value, int)
    with pytest.raises(TypeError, match="Field 'value' expects int"):
        GridClue(loc="a1", value="seven")  # type: ignore[arg-type]


def test_differently_namespaced_instances_are_never_equal() -> None:
    a = Clue(loc="a1", value=7)
    b = Clue.in_namespace("grid")(loc="a1", value=7)
    assert a != b
    assert len({a, b}) == 2


def test_renamespacing_a_clone_replaces_rather_than_nests() -> None:
    once = Clue.in_namespace("grid")
    twice = once.in_namespace("other")
    assert twice.get_name() == "other_clue"


def test_clones_coexist_in_one_program_and_round_trip() -> None:
    GridClue = Clue.in_namespace("grid")
    program = ASPProgram()
    program.fact(Clue(loc="a1", value=7), GridClue(loc="b2", value=3))
    model = next(iter(program.solve()))
    assert [(c.loc, c.value) for c in model.atoms(Clue)] == [("a1", 7)]
    assert [(c.loc, c.value) for c in model.atoms(GridClue)] == [("b2", 3)]


def test_define_classes_clone_too() -> None:
    Edge = Predicate.define("edge", ["a", "b"], show=False)
    GridEdge = Edge.in_namespace("grid")
    assert GridEdge.get_name() == "grid_edge"
    assert GridEdge(a=1, b=2).render() == "grid_edge(1, 2)"


def test_namespace_validation_applies() -> None:
    with pytest.raises(ValueError, match="Namespace"):
        Clue.in_namespace("Bad Namespace!")
