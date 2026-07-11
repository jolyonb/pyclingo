"""
Tests for class-syntax predicates: statically typed fields, one creation path
shared with define().
"""

import pytest

from aspalchemy import ASPProgram, Predicate, PredicateField


class Person(Predicate):
    name: PredicateField
    age: PredicateField


class Plumbing(Predicate, name="pipe_seg", namespace="grid", show=False):
    loc: PredicateField


def test_name_derives_from_class_name() -> None:
    assert Person.get_name() == "person"
    assert Person.get_arity() == 2


def test_class_kwargs_set_name_namespace_and_visibility() -> None:
    assert Plumbing.get_name() == "grid_pipe_seg"
    assert Plumbing.shown_by_default() is False


def test_renders_and_coerces_like_define() -> None:
    assert Person(name="john", age=30).render() == 'person("john", 30)'
    assert Person("mary", 25).render() == 'person("mary", 25)'  # positional works


def test_equality_semantics_preserved() -> None:
    assert Person("j", 1) == Person("j", 1)
    assert Person("j", 1) != Person("k", 1)
    assert len({Person("j", 1), Person("j", 1)}) == 1


def test_schema_validation_fires_at_class_creation() -> None:
    with pytest.raises(ValueError, match="lowercase"):

        class Bad(Predicate, name="BadName"):
            x: PredicateField

    with pytest.raises(ValueError, match="shadow"):

        class Shadow(Predicate):
            render: PredicateField  # type: ignore[assignment]


def test_nullary_class_syntax() -> None:
    class Flag(Predicate, show=False):
        pass

    assert Flag().render() == "flag"


def test_round_trips_typed() -> None:
    program = ASPProgram()
    program.fact(Person(name="john", age=30))
    model = next(iter(program.solve()))
    people = model.atoms(Person)
    assert people == [Person(name="john", age=30)]
    assert people[0].age.value == 30  # type: ignore[union-attr]


def test_define_uses_the_same_creation_path() -> None:
    Edge = Predicate.define("edge", ["a", "b"], show=False)
    assert Edge.get_name() == "edge"
    assert Edge(a=1, b=2).render() == "edge(1, 2)"
    assert Edge.shown_by_default() is False


def test_default_name_snake_cases_the_class_name() -> None:
    class HasSymbol(Predicate, show=False):
        loc: PredicateField

    assert HasSymbol.get_name() == "has_symbol"
