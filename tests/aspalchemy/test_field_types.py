"""
Tests for Field[T]-typed predicate slots: per-field validation on write,
plain-Python values on read, rule authoring unimpeded.
"""

import dataclasses
import types
from typing import Any, ClassVar

import pytest

from aspalchemy import ASPProgram, Field, Number, Predicate, PredicateArg, String, Variable


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
        anything: Field[PredicateArg]  # polymorphic slot: any term in, plain read out

    m = Mixed(tag="t", anything=5)
    assert m.tag == "t"
    assert m.anything == 5 and isinstance(m.anything, int)  # dot read is plain, like any field
    assert isinstance(m["anything"], Number)  # the Term view stays on bracket access


def test_polymorphic_slot_reads_plain_and_unwraps_written_wrappers() -> None:
    # A Field[PredicateArg] slot reads back plain Python for every write shape: a bare
    # int/str and an already-wrapped Number/String all land as plain values,
    # exactly as a typed field would, while brackets keep the Term view.
    class Poly(Predicate, show=False):
        x: Field[PredicateArg]

    assert Poly(x=5).x == 5 and isinstance(Poly(x=5).x, int)
    assert Poly(x="a").x == "a" and isinstance(Poly(x="a").x, str)
    assert Poly(x=Number(5)).x == 5 and isinstance(Poly(x=Number(5)).x, int)
    assert Poly(x=String("a")).x == "a" and isinstance(Poly(x=String("a")).x, str)
    assert isinstance(Poly(x=5)["x"], Number)  # bracket keeps the Term view


def test_repr_is_plain_python_canonical_is_the_asp_named_form() -> None:
    # repr() is what you'd type to recreate the atom — plain values, no Number/
    # String wrappers leaking out. canonical_str() is the ASP named form. Both
    # keep the internal wrappers hidden; they differ only in Python vs ASP shape.
    class Poly(Predicate, show=False):
        x: Field[PredicateArg]
        y: Field[PredicateArg]

    p = Poly(x=5, y="hi")
    assert repr(p) == "Poly(x=5, y='hi')"
    assert p.canonical_str() == 'poly(x=5, y="hi")'


def test_repr_of_a_non_ground_field_uses_the_term_repr() -> None:
    # A ground field reprs plain; a non-ground one (here a Variable) reprs by
    # the term's own repr — so repr stays reconstructable in both cases.
    class Poly(Predicate, show=False):
        x: Field[PredicateArg]

    assert repr(Poly(x=Variable("X"))) == "Poly(x=Variable('X'))"


def test_polymorphic_slot_holds_a_nested_atom_and_rejects_bool() -> None:
    class Poly(Predicate, show=False):
        x: Field[PredicateArg]

    inner = Clue(loc="a1", value=7)
    holder = Poly(x=inner)
    assert holder.x == inner  # a nested atom passes through and reads back
    assert holder.render() == 'poly(clue("a1", 7))'
    with pytest.raises(TypeError):  # bool is not a valid ASP integer, even here
        Poly(x=True)


def test_field_defaults_are_used_and_validated() -> None:
    # A field may carry a default value, assigned beside the annotation (the
    # dataclass spelling, documented in docs/predicates.md). It fills in when
    # the argument is omitted, an explicit value overrides it, and BOTH routes
    # pass the same per-field write validation — a wrong-typed default is
    # caught at the first construction that relies on it.
    class Tagged(Predicate, show=False):
        loc: Field[int]
        kind: Field[str] = "plain"  # type: ignore[assignment]

    assert Tagged(loc=1).kind == "plain"
    assert Tagged(loc=1).render() == 'tagged(1, "plain")'
    assert Tagged(loc=1, kind="x").render() == 'tagged(1, "x")'
    with pytest.raises(TypeError, match="Field 'kind' expects str"):
        Tagged(loc=1, kind=7)  # type: ignore[arg-type]

    class BadDefault(Predicate, show=False):
        loc: Field[int]
        kind: Field[str] = 7  # type: ignore[assignment]

    with pytest.raises(TypeError, match="Field 'kind' expects str"):
        BadDefault(loc=1)
    assert BadDefault(loc=1, kind="x").render() == 'bad_default(1, "x")'


def test_redeclaring_an_inherited_field_is_refused() -> None:
    # A subclass may only ADD fields; re-typing an inherited one is refused with
    # a teaching error (rather than a leaky dataclass "default" collision).
    class Base(Predicate, show=False):
        a: Field[int]
        b: Field[int]

    with pytest.raises(TypeError, match=r"re-declares the inherited field 'a'"):

        class Sub(Base, show=False):
            a: Field[str]  # type: ignore[assignment]


def test_class_data_shadowing_an_inherited_field_is_refused() -> None:
    # The other spellings of a re-declaration: a ClassVar re-annotating an
    # inherited field would make dataclass() silently DELETE it from the
    # signature (wrong arity, wrong render), and a bare assignment would
    # shadow the base's Field descriptor in the MRO, so writes to that field
    # would skip validation entirely. Both are refused at class creation.
    class Base(Predicate, show=False):
        a: Field[int]
        b: Field[int]

    with pytest.raises(TypeError, match=r"shadows the inherited field 'a'"):

        class ViaClassVar(Base, show=False):
            a: ClassVar[int] = 5  # type: ignore[misc]

    with pytest.raises(TypeError, match=r"shadows the inherited field 'a'"):

        class ViaBareValue(Base, show=False):
            a = 99  # type: ignore[assignment]


def test_new_field_shadowing_inherited_class_data_is_refused() -> None:
    # The mirror collision: a subclass field named after inherited class data
    # would make dataclass() read the base's value as a silent default nobody
    # wrote. An explicit default assigned in the subclass body stays legal.
    class Base(Predicate, show=False):
        a: Field[int]
        tag: ClassVar[int] = 7

    with pytest.raises(TypeError, match=r"'tag' is inherited class data"):

        class Sub(Base, show=False):
            tag: Field[int]  # type: ignore[misc]

    class Deliberate(Base, show=False):
        tag: Field[int] = 7  # type: ignore[assignment, misc]

    assert Deliberate(a=1).render() == "deliberate(1, 7)"


def test_non_field_annotation_is_refused() -> None:
    # A predicate's arguments are exactly its Field[...] slots. Any other
    # annotation — a plain type a caller forgot to wrap, defaulted or not — is
    # refused at class creation, naming the fix, rather than silently dropped
    # from the signature.
    with pytest.raises(TypeError, match=r"not a predicate field.*Field\[int\].*Field\[PredicateArg\]"):

        class Tagged(Predicate, show=False):
            loc: Field[int]
            note: str = "hi"

    with pytest.raises(TypeError, match="not a predicate field"):

        class Sparse(Predicate, show=False):
            loc: Field[int]
            absent: int


def test_non_argument_data_uses_classvar_or_a_bare_attribute() -> None:
    # The supported ways to carry non-argument class data: a ClassVar (typed
    # constant) or a bare unannotated assignment (which never enters
    # __annotations__, so it is not a candidate field at all).
    class Cfg(Predicate, show=False):
        loc: Field[int]
        KIND: ClassVar[str] = "grid"
        helper = 42

    assert Cfg.field_names() == ["loc"] and Cfg.get_arity() == 1
    cfg = Cfg(loc=3)
    assert cfg.render() == "cfg(3)"
    assert Cfg.KIND == "grid" and cfg.helper == 42


def test_classvar_shadowing_a_predicate_member_is_refused() -> None:
    # A ClassVar is allowed, but not one whose name would shadow a Predicate
    # method/attribute (which would silently break the API on instances).
    with pytest.raises(ValueError, match=r"ClassVar 'render' would shadow"):

        class Bad(Predicate, show=False):
            loc: Field[int]
            render: ClassVar[str] = "boom"  # type: ignore[assignment]


def test_bare_field_annotation_is_refused() -> None:
    # An unsubscripted Field carries no ground type and is always a mistake.
    with pytest.raises(TypeError, match=r"bare Field.*needs a type argument"):

        class Bad(Predicate, show=False):
            x: Field


def test_bare_predicatearg_annotation_points_at_field_predicatearg() -> None:
    # PredicateArg is a type, not a field — a bare `x: PredicateArg` (forgetting
    # the Field wrapper) is refused with a targeted pointer: every field is a
    # Field[...].
    with pytest.raises(TypeError, match=r"spelled Field\[PredicateArg\], not a bare PredicateArg"):

        class Bad(Predicate, show=False):
            x: PredicateArg


def test_subclass_of_subclass_inherits_fields_in_mro_order() -> None:
    # A Predicate subclass may itself be subclassed to add fields. The cached
    # _field_names must list inherited fields first, then own, across every
    # level — and inherited descriptors (typed AND polymorphic) keep working on
    # the deeper instances.
    class Base(Predicate, show=False):
        a: Field[int]
        b: Field[PredicateArg]  # polymorphic, inherited two levels down

    class Middle(Base, show=False):
        c: Field[str]

    class Leaf(Middle, show=False):
        d: Field[int]

    assert Base.field_names() == ["a", "b"]
    assert Middle.field_names() == ["a", "b", "c"]
    assert Leaf.field_names() == ["a", "b", "c", "d"]
    assert Leaf.get_arity() == 4

    leaf = Leaf(a=1, b="poly", c="x", d=2)
    assert leaf.render() == 'leaf(1, "poly", "x", 2)'
    # inherited fields read plain — the typed one and the polymorphic one alike
    assert leaf.a == 1 and isinstance(leaf.a, int)
    assert leaf.b == "poly" and isinstance(leaf.b, str)
    assert isinstance(leaf["b"], String)  # bracket keeps the Term view
    # own field validation still fires through the inherited machinery
    with pytest.raises(TypeError, match="Field 'd' expects int"):
        Leaf(a=1, b="poly", c="x", d="two")  # type: ignore[arg-type]


def test_argument_fields_returns_real_dataclass_fields() -> None:
    # The public shim hands back genuine dataclasses.Field objects, in the same
    # order as field_names() — a future name-only replacement would break this.
    fields = Clue.argument_fields()
    assert all(isinstance(f, dataclasses.Field) for f in fields)
    assert [f.name for f in fields] == Clue.field_names()


def test_field_any_is_refused() -> None:
    # Field[PredicateArg] is the one polymorphic spelling; Field[Any] would erase the
    # read typing, so it is refused with a pointer back to Field[PredicateArg].
    with pytest.raises(TypeError, match=r"Field\[Any\] and hand-written unions are not accepted"):

        class Bad(Predicate):
            x: Field[Any]


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
    assert m.anything == 5  # type: ignore[attr-defined]  # untyped slot reads plain now
    assert isinstance(m["anything"], Number)  # the Term view stays on bracket access
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
