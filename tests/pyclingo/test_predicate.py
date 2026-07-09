import pytest

from pyclingo import ASPProgram, Comparison, DefaultNegation, Field, Number, Predicate, Variable


class CluePred(Predicate):
    loc: Field[str]
    value: Field[int]


def test_definition_sites_are_recorded_for_both_syntaxes() -> None:
    # Collision errors disambiguate same-named classes by definition site,
    # so both creation paths must record one pointing into user code
    class_syntax_at = CluePred._defined_at  # the module-level class statement above
    assert class_syntax_at is not None and class_syntax_at.filename == __file__
    defined = Predicate.define("p_site", ["x"])
    assert defined._defined_at is not None and defined._defined_at.filename == __file__
    cloned = defined.in_namespace("ns_site")
    assert cloned._defined_at is not None and cloned._defined_at.filename == __file__


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
        Predicate.define("p", ["items"])
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


def test_items_returns_field_name_term_pairs() -> None:
    P = Predicate.define("p", ["x", "y"])
    d = dict(P(x=1, y=2).items())
    assert set(d) == {"x", "y"}
    assert isinstance(d["x"], Number) and d["x"].value == 1
    assert isinstance(d["y"], Number) and d["y"].value == 2


def test_ne_non_predicate_returns_not_implemented() -> None:
    P = Predicate.define("p", ["x"])
    assert P(x=1).__ne__(5) is NotImplemented
    # Reflection against a Variable builds an ASP inequality comparison
    comparison = P(x=1) != Variable("X")
    assert isinstance(comparison, Comparison)
    assert "!=" in comparison.render()
