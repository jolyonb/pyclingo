import pytest

from pyclingo import ASPProgram, DefaultNegation, Predicate


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
