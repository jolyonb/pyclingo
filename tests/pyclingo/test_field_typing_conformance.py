"""
Typing-conformance file for Field[T]: this module contains no runtime
assertions — its job is to be type-checked by the mypy and pyright hooks.
If the descriptor's read/write typing breaks, the checkers fail the build.
"""

from pyclingo import Field, Predicate, Variable


class Person(Predicate):
    name: Field[str]
    age: Field[int]


def ground_reads_are_typed() -> tuple[str, int]:
    person = Person(name="john", age=30)
    # These assignments only type-check if reads carry the ground types
    the_name: str = person.name
    the_age: int = person.age
    return the_name, the_age


def rule_atoms_accept_terms() -> Person:
    x = Variable("X")
    return Person(name=x, age=x + 1)
