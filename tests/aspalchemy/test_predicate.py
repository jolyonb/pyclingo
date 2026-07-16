import copy
import dataclasses
import pickle

import pytest

from aspalchemy import ASPProgram, Comparison, DefaultNegation, Field, Number, Predicate, PredicateArg, Variable, pool


class CluePred(Predicate):
    loc: Field[str]
    value: Field[int]


class UntypedPkl(Predicate):
    x: Field[PredicateArg]


def test_definition_sites_are_recorded_for_both_syntaxes() -> None:
    # Collision errors disambiguate same-named classes by definition site,
    # so both creation paths must record one pointing into user code
    class_syntax_at = CluePred._defined_at  # the module-level class statement above
    assert class_syntax_at is not None and class_syntax_at.filename == __file__
    defined = Predicate.define("p_site", ["x"])
    assert defined._defined_at is not None and defined._defined_at.filename == __file__
    cloned = defined.in_namespace("ns_site")
    assert cloned._defined_at is not None and cloned._defined_at.filename == __file__


def test_runtime_built_classes_claim_the_callers_module() -> None:
    # Like _defined_at, __module__ must point at user code, not the
    # class-creation machinery (repr and pickle errors name it)
    defined = Predicate.define("p_mod", ["x"])
    assert defined.__module__ == __name__
    assert defined.in_namespace("ns_mod").__module__ == __name__


def test_runtime_built_atoms_refuse_pickle_with_teaching() -> None:
    # A define()/in_namespace() class cannot be found by name on import;
    # its atoms refuse loudly, teaching render()-based transport
    defined = Predicate.define("p_pkl", ["x"])
    with pytest.raises(TypeError, match=r"do not pickle.*render\(\)"):
        pickle.dumps(defined(x=1))


def test_deepcopy_works_where_pickle_refuses() -> None:
    # Copy and pickle are separate paths: __copy__/__deepcopy__ return self
    # and never consult the pickle gate, so a runtime-built atom deepcopies
    # fine while pickling it refuses
    defined = Predicate.define("p_copy_not_pkl", ["x"])
    atom = defined(x=1)
    assert copy.deepcopy(atom) is atom
    with pytest.raises(TypeError, match="do not pickle"):
        pickle.dumps(atom)


def test_nested_runtime_atom_refuses_pickle_through_a_findable_one() -> None:
    # The findability gate applies wherever pickle reaches: a class-syntax
    # atom holding a define()-built atom in a field refuses at the nested atom
    inner_class = Predicate.define("p_inner_pkl", ["x"])
    outer = UntypedPkl(x=inner_class(x=1))
    with pytest.raises(TypeError, match="do not pickle"):
        pickle.dumps(outer)


def test_class_syntax_atoms_round_trip_through_pickle() -> None:
    # A findable class pickles by the default machinery; the Values inside
    # re-intern, so identity guarantees survive the round trip
    atom = CluePred(loc="a1", value=7)
    loaded = pickle.loads(pickle.dumps(atom))
    assert loaded == atom and type(loaded) is CluePred
    negated = pickle.loads(pickle.dumps(-atom))
    assert negated.negated is True and negated == -atom
    untyped = pickle.loads(pickle.dumps(UntypedPkl(x=5)))
    assert untyped["x"] is Number(5)  # the stored Number is the cache resident again


def test_copies_of_an_atom_are_the_atom() -> None:
    # Predicates are immutable data: copy and deepcopy return the original,
    # exactly as for interned Values
    atom = CluePred(loc="a1", value=7)
    assert copy.copy(atom) is atom
    assert copy.deepcopy(atom) is atom


def test_negation_builds_a_distinct_atom_despite_copy_identity() -> None:
    # __neg__ makes its own duplicate for the sign flip; __copy__ returning
    # self must never let the flip mutate the original
    atom = CluePred(loc="a1", value=7)
    negated = -atom
    assert negated is not atom
    assert negated.negated is True and atom.negated is False


def test_render_is_cached_on_the_frozen_instance() -> None:
    # render() stashes its result on first call — the rendered form is the
    # atom's canonical identity (eq/hash compare it), so repeated hashing
    # must not re-walk the tree. Identity of the returned string pins that
    # the second call is the stash, not a recomputation; frozenness is what
    # makes the stash sound (fields can never change under it).
    atom = CluePred(loc="a1", value=7)
    first = atom.render()
    assert atom.render() is first


def test_render_cache_never_leaks_through_atom_producing_paths() -> None:
    # Every path that hands back a DIFFERENT atom must not inherit the
    # cached render of the atom it came from: __neg__'s field-sharing
    # duplicate skips the stash (the sign changes the render), double
    # negation re-renders the positive form, copy.replace() rebuilds
    # through the constructor, and a pickle round trip must still render
    # correctly whether or not the cache was populated when pickled.
    atom = CluePred(loc="a1", value=7)
    assert atom.render() == 'clue_pred("a1", 7)'  # populate the cache
    negated = -atom
    assert negated.render() == '-clue_pred("a1", 7)'
    assert (-negated).render() == 'clue_pred("a1", 7)'
    assert copy.replace(atom, value=8).render() == 'clue_pred("a1", 8)'
    assert copy.replace(negated, value=8).render() == '-clue_pred("a1", 8)'
    assert pickle.loads(pickle.dumps(atom)).render() == 'clue_pred("a1", 7)'
    fresh = pickle.loads(pickle.dumps(CluePred(loc="b2", value=1)))  # cache never populated
    assert fresh.render() == 'clue_pred("b2", 1)'


def test_predicate_default_negation_operator() -> None:
    """Test the ~ operator creates DefaultNegation."""
    Person = Predicate.define("person", ["name"])
    person = Person(name="john")

    not_person = ~person

    assert isinstance(not_person, DefaultNegation)
    assert not_person.term == person


def test_nullary_predicate_representations() -> None:
    """Nullary atoms render bare in ASP; parens mark predicate-ness elsewhere."""
    Flag = Predicate.define("flag", [])
    f = Flag()
    assert f.render() == "flag"  # canonical ASP: no empty parens
    assert f.canonical_str() == "flag()"  # parens mark predicate-ness in the canonical format
    assert repr(f) == "flag()"

    program = ASPProgram()
    program.fact(f)
    assert "\nflag.\n" in program.render()
    assert next(iter(program.solve())).atoms(Flag) == [Flag()]


def test_define_validates_namespaces() -> None:
    with pytest.raises(ValueError, match="Namespace"):
        Predicate.define("p", ["x"], namespace="Bad Namespace!")
    Predicate.define("p", ["x"], namespace="grid_2")  # valid


def test_define_validates_field_names() -> None:
    with pytest.raises(ValueError, match="underscore"):
        Predicate.define("p", ["_x"])  # would be silently dropped from the arity
    with pytest.raises(ValueError, match="shadow"):
        Predicate.define("p", ["render"])
    with pytest.raises(ValueError, match="shadow"):
        Predicate.define("p", ["arguments"])
    with pytest.raises(ValueError, match="identifier"):
        Predicate.define("p", ["not valid"])


def test_name_case_is_preserved() -> None:
    P = Predicate.define("myPred", ["x"])
    assert P(x=1).render() == "myPred(1)"
    assert P.get_name() == "myPred"


def test_duplicate_field_names_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate field name"):
        Predicate.define("edge", ["a", "a"])


def test_keyword_and_reserved_names_rejected() -> None:
    with pytest.raises(ValueError, match="keyword"):
        Predicate.define("k", ["class"])
    with pytest.raises(ValueError, match="reserved"):
        Predicate.define("not", ["a"])


def test_base_predicate_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError, match="cannot be instantiated directly"):
        Predicate()


def test_non_ascii_names_rejected() -> None:
    # gringo's lexer is ASCII-only; its error path crashes on multi-byte
    # identifiers, so they must die at definition
    with pytest.raises(ValueError, match="ASCII"):
        Predicate.define("ärger", ["x"])
    with pytest.raises(ValueError, match="ASCII"):
        Predicate.define("p", ["fëld"])
    with pytest.raises(ValueError, match="ASCII"):
        Predicate.define("p", ["x"], namespace="ünter")


def test_field_class_access_returns_descriptor() -> None:
    """Reading a Field off the class (not an instance) yields the descriptor itself."""
    assert isinstance(CluePred.loc, Field)


def test_field_missing_value_raises_attribute_error() -> None:
    """A field never stored (instance built without __init__) reads as a missing attribute."""
    c = object.__new__(CluePred)
    assert getattr(c, "loc", "sentinel") == "sentinel"
    with pytest.raises(AttributeError):
        c.loc  # noqa: B018 (the attribute access is the act under test)


def test_predicate_name_rejects_invalid_characters() -> None:
    with pytest.raises(ValueError, match="letters, digits, and underscores"):
        Predicate.define("p-bad", ["x"])


def test_predicate_argument_rejects_unsupported_type() -> None:
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="must be a Value"):
        P(x=1.5)  # type: ignore[arg-type]


def test_getitem_unknown_field_raises_key_error() -> None:
    P = Predicate.define("p", ["x"])
    with pytest.raises(KeyError, match="no field named 'nope'"):
        P(x=1)["nope"]


def test_ne_non_predicate_returns_not_implemented() -> None:
    P = Predicate.define("p", ["x"])
    assert P(x=1).__ne__(5) is NotImplemented
    # Reflection against a Variable builds an ASP inequality comparison
    comparison = P(x=1) != Variable("X")
    assert isinstance(comparison, Comparison)
    assert "!=" in comparison.render()


def test_define_rejects_a_bare_string_of_field_names() -> None:
    # list("loc") is ['l', 'o', 'c']: a silently wrong arity-3 predicate
    with pytest.raises(TypeError, match="one field per character"):
        Predicate.define("r_bare", "loc")  # type: ignore[arg-type]


def test_define_show_must_be_a_bool() -> None:
    # show=None silently meant hidden
    with pytest.raises(TypeError, match="show must be a bool"):
        Predicate.define("p_shownone", ["x"], show=None)  # type: ignore[arg-type]


def test_pool_alternation_cannot_evade_the_nesting_cap() -> None:
    # Depth rides through explicit pools: a Predicate <-> pool chain hits
    # the teaching cap instead of a raw RecursionError mid-walk
    Wrap = Predicate.define("wrap_pool_deep", ["x"])
    chain: object = Predicate.define("nil_pool_deep", [], show=False)()
    with pytest.raises(ValueError, match="indexed facts"):
        for _ in range(Predicate.MAX_DEPTH):
            chain = Wrap(x=pool([chain, 0]))  # type: ignore[list-item]


def test_deep_predicate_nesting_rejected_at_construction() -> None:
    # Mirrors Expression.MAX_DEPTH: a linked-list encoding built in a loop
    # would die mid-walk with a raw RecursionError
    Wrap = Predicate.define("wrap_deep", ["inner"])
    chain: Predicate = Predicate.define("nil_deep", [], show=False)()
    for _ in range(Predicate.MAX_DEPTH - 1):
        chain = Wrap(inner=chain)
    chain.render()  # at the cap: walkers still fine
    with pytest.raises(ValueError, match="indexed facts"):
        Wrap(inner=chain)


def test_copy_replace_preserves_the_sign() -> None:
    # copy.replace routes through __replace__, which re-applies the sign
    # the fields-based reconstruction would silently drop
    P = Predicate.define("p_repl", ["x", "y"])
    negated = -P(x=1, y=2)
    replaced = copy.replace(negated, y=3)
    assert replaced == -P(x=1, y=3)
    assert replaced.negated is True
    positive = copy.replace(P(x=1, y=2), y=3)
    assert positive == P(x=1, y=3) and positive.negated is False


def test_dataclasses_replace_drops_the_sign_as_documented() -> None:
    # dataclasses.replace bypasses __replace__ entirely (its reconstruction
    # is fields-based; no stdlib hook exists), so it DOES drop the sign —
    # documented on __replace__ and in CLAUDE.md; use copy.replace. This
    # pin records the known-wrong behavior: if a future stdlib routes
    # dataclasses.replace through __replace__, it fails and we get to
    # delete the caveat.
    P = Predicate.define("p_repl_dc", ["x", "y"])
    replaced = dataclasses.replace(-P(x=1, y=2), y=3)  # type: ignore[call-arg]  # fields unknowable for define()
    assert replaced == P(x=1, y=3)  # sign silently gone: the documented trap


def test_disjunction_attempt_teaches_the_modeled_spellings() -> None:
    P = Predicate.define("p_disj", ["x"])
    Q = Predicate.define("q_disj", ["x"])
    with pytest.raises(TypeError, match=r"disjunctive heads.*Choice with at_least\(1\)"):
        P(x=1) | Q(x=1)  # type: ignore[operator]


def test_tuple_arguments_teach_the_named_predicate_idiom() -> None:
    # The read side already taught this for model atoms; the write side
    # speaks the same sentence
    P = Predicate.define("p_tuple_arg", ["x"])
    with pytest.raises(TypeError, match=r"the tuple \(1, 2\).*wrap it in a named predicate"):
        P(x=(1, 2))  # type: ignore[arg-type]
