from pyclingo.predicate import DefaultNegation, Predicate


def test_predicate_default_negation_operator() -> None:
    """Test the ~ operator creates DefaultNegation."""
    Person = Predicate.define("person", ["name"])
    person = Person(name="john")

    not_person = ~person

    assert isinstance(not_person, DefaultNegation)
    assert not_person.term == person
