"""
Tests for in_namespace(): cached namespaced copies of predicate classes.
"""

import gc
import threading
import weakref

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


def test_clone_churn_is_collectable() -> None:
    # The clone cache lives in the base class's own __dict__: dropping the
    # base frees its clones, so a define()+in_namespace() loop cannot pin
    # classes forever through a process-global cache
    base = Predicate.define("churn_probe", ["x"])
    clone = base.in_namespace("ns_churn")
    assert base.in_namespace("ns_churn") is clone  # repeat-call identity while live
    base_ref, clone_ref = weakref.ref(base), weakref.ref(clone)
    del base, clone
    gc.collect()
    assert base_ref() is None
    assert clone_ref() is None


def test_concurrent_cloning_agrees_on_one_class() -> None:
    # Racing in_namespace() callers must all hold the same clone class: two
    # distinct classes sharing (name, arity) would trip the collision check
    base = Predicate.define("race_clone", ["x"])
    results: list[type[Predicate]] = []
    barrier = threading.Barrier(8)

    def clone() -> None:
        barrier.wait()
        results.append(base.in_namespace("ns_race"))

    threads = [threading.Thread(target=clone) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 8
    assert len({id(c) for c in results}) == 1
