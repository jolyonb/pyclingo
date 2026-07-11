"""
Tests for Field[T]-typed predicate slots: per-field validation on write,
plain-Python values on read, rule authoring unimpeded.
"""

import dataclasses
import types
from typing import ClassVar

import pytest

from aspalchemy import ASPProgram, Field, Number, Predicate, PredicateField, String, Variable


class Clue(Predicate):
    loc: Field[str]
    value: Field[int]


class Wrap(Predicate):
    inner: Field[Clue]


def test_ground_reads_are_plain_values() -> None:
    clue = Clue(loc="a1", value=7)
    assert clue.loc == "a1" and isinstance(clue.loc, str)
    assert clue.value == 7 and isinstance(clue.value, int)


def test_square_bracket_access_serves_the_term_view() -> None:
    # Attribute access (clue.value) is the typed plain-Python view; square
    # brackets (clue["value"]) and all internal machinery read Terms via
    # read_as_term, so pred[...].value works identically on classic and
    # Field-typed predicates
    clue = Clue(loc="a1", value=7)
    assert isinstance(clue["value"], Number) and clue["value"].value == 7
    assert isinstance(clue["loc"], String) and clue["loc"].value == "a1"
    assert clue.read_as_term("value") is clue["value"]  # cached wrapper


def test_wrappers_normalize_to_plain_values() -> None:
    clue = Clue(loc=String("a1"), value=Number(7))  # type: ignore[arg-type]
    assert clue.loc == "a1" and clue.value == 7
    assert clue == Clue(loc="a1", value=7)


def test_wrong_ground_type_rejected_with_field_name() -> None:
    with pytest.raises(TypeError, match="Field 'value' expects int"):
        Clue(loc="a1", value="seven")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Field 'loc' expects str"):
        Clue(loc=3, value=7)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="expects int"):
        Clue(loc="a1", value=True)  # type: ignore[arg-type]


def test_ground_validation_still_applies() -> None:
    with pytest.raises(ValueError, match="integer range"):
        Clue(loc="a1", value=2**40)
    with pytest.raises(ValueError, match="backslash"):
        Clue(loc="bad\\nname", value=1)


def test_rule_authoring_unimpeded() -> None:
    X, N = Variable("X"), Variable("N")
    atom = Clue(loc=X, value=N + 1)
    assert atom.render() == "clue(X, N + 1)"
    assert not atom.is_grounded
    assert atom.collect_variables() == {"X", "N"}


def test_rendering_and_canonical_match_classic_predicates() -> None:
    typed = Clue(loc="a1", value=7)
    assert typed.render() == 'clue("a1", 7)'
    assert typed.canonical_str() == 'clue(loc="a1", value=7)'


def test_nested_predicate_field() -> None:
    w = Wrap(inner=Clue(loc="a1", value=7))
    assert w.render() == 'wrap(clue("a1", 7))'
    with pytest.raises(TypeError, match="Field 'inner' expects Clue"):
        Wrap(inner=5)  # type: ignore[arg-type]


def test_frozen() -> None:
    clue = Clue(loc="a1", value=7)
    with pytest.raises(dataclasses.FrozenInstanceError):
        clue.value = 8  # type: ignore[misc]


def test_solve_round_trip_returns_plain_values() -> None:
    program = ASPProgram()
    program.fact(Clue(loc="a1", value=7), Clue(loc="b2", value=3))
    model = next(iter(program.solve()))
    clues = sorted(model.atoms(Clue), key=lambda c: c.loc)
    assert [(c.loc, c.value) for c in clues] == [("a1", 7), ("b2", 3)]
    assert clues[0].value + clues[1].value == 10  # plain ints, plain arithmetic


def test_mixed_field_kinds_in_one_class() -> None:
    class Mixed(Predicate, show=False):
        tag: Field[str]
        anything: PredicateField  # classic slot keeps the old behavior

    m = Mixed(tag="t", anything=5)
    assert m.tag == "t"
    assert isinstance(m["anything"], Number)  # classic slot wraps as before


def test_unsupported_ground_type_rejected() -> None:
    with pytest.raises(TypeError, match="ground type must be"):

        class Bad(Predicate):
            x: Field[float]  # type: ignore[type-var]


class RawClue(Predicate, name="raw_clue"):
    loc: Field[str]
    value: Field[int]


def test_define_with_typed_fields() -> None:
    TypedClue = Predicate.define("typed_clue", {"loc": str, "value": int})
    clue = TypedClue(loc="a1", value=7)
    assert clue.loc == "a1" and clue.value == 7  # type: ignore[attr-defined]
    with pytest.raises(TypeError, match="Field 'value' expects int"):
        TypedClue(loc="a1", value="seven")


def test_solution_with_unexpected_type_fails_loudly() -> None:
    # The converter is an untrusted boundary: raw_asp (or a program bug) can
    # produce an atom whose argument type contradicts the declared schema, and
    # loading it must fail at the load, not corrupt downstream
    program = ASPProgram()
    program.raw_asp('raw_clue("a1", "seven").', predicates=[RawClue])
    with pytest.raises(TypeError, match=r"raw_clue.*cannot be read back.*Field 'value' expects int, got str"):
        list(program.solve())


def test_solution_with_expected_types_loads_plain() -> None:
    program = ASPProgram()
    program.raw_asp('raw_clue("a1", 7).', predicates=[RawClue])
    model = next(iter(program.solve()))
    clue = model.atoms(RawClue)[0]
    assert clue.loc == "a1" and clue.value == 7


def test_classvar_helpers_are_not_fields() -> None:
    class WithHelper(Predicate, show=False):
        loc: Field[str]
        _threshold: ClassVar[int] = 3

    assert WithHelper.get_arity() == 1
    assert WithHelper(loc="a1").render() == 'with_helper("a1")'
    assert WithHelper._threshold == 3


def test_define_mixed_schema_with_untyped_slots() -> None:
    Mixed = Predicate.define("mixed_schema", {"tag": str, "anything": None})
    m = Mixed(tag="t", anything=5)
    assert m.tag == "t"  # type: ignore[attr-defined]
    assert isinstance(m["anything"], Number)  # untyped slot behaves classically
    with pytest.raises(TypeError, match="Field 'tag' expects str"):
        Mixed(tag=1, anything=5)


def test_stringified_field_annotations_rejected() -> None:
    # "from __future__ import annotations" stringifies annotations; silently
    # skipping descriptor installation would drop validation and typed reads
    with pytest.raises(TypeError, match="from __future__ import annotations"):
        types.new_class(
            "StringAnnotated",
            bases=(Predicate,),
            exec_body=lambda ns: ns.__setitem__("__annotations__", {"points": "Field[int]"}),
        )
