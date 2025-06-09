from pyclingo.negation import ClassicalNegation, DefaultNegation
from pyclingo.predicate import Predicate


def test_predicate_classical_negation_operator() -> None:
    """Test the - operator creates ClassicalNegation."""
    Person = Predicate.define("person", ["name"])
    person = Person(name="john")

    neg_person = -person

    assert isinstance(neg_person, ClassicalNegation)
    assert neg_person.term == person


def test_predicate_default_negation_operator() -> None:
    """Test the ~ operator creates DefaultNegation."""
    Person = Predicate.define("person", ["name"])
    person = Person(name="john")

    not_person = ~person

    assert isinstance(not_person, DefaultNegation)
    assert not_person.term == person
