"""
Tests for Symbol: plain symbolic constant terms like the n in direction(n).
"""

import pytest

from pyclingo import ASPProgram, ExplicitPool, Symbol
from pyclingo.predicate import Predicate
from pyclingo.value import String


def test_renders_unquoted() -> None:
    P = Predicate.define("direction", ["name"])
    assert P(name=Symbol("n")).render() == "direction(n)"
    assert P(name="n").render() == 'direction("n")'  # strings stay quoted


def test_distinct_from_string_constant() -> None:
    assert Symbol("n") is not String("n")
    assert Symbol("n").render() != String("n").render()


def test_cached_like_other_values() -> None:
    assert Symbol("n") is Symbol("n")
    assert Symbol("n") is not Symbol("s")


def test_validation() -> None:
    with pytest.raises(ValueError, match="must start with a lowercase letter"):
        Symbol("North")
    with pytest.raises(ValueError, match="must start with a lowercase letter"):
        Symbol("")
    with pytest.raises(ValueError, match="letters, digits, and underscores"):
        Symbol("n-w")


def test_works_in_pools() -> None:
    pool = ExplicitPool([Symbol("n"), Symbol("s"), Symbol("e"), Symbol("w")])
    assert pool.render() == "(n; s; e; w)"


def test_no_registration_required() -> None:
    # Unlike DefinedConstant (#const), a Symbol needs no define_constant
    program = ASPProgram()
    P = Predicate.define("direction", ["name"])
    program.fact(P(name=Symbol("n")))
    assert "direction(n)." in program.render()


def test_round_trips_through_solve() -> None:
    program = ASPProgram()
    P = Predicate.define("direction", ["name"])
    program.fact(P(name=Symbol("n")), P(name=Symbol("s")))
    solutions = list(program.solve())
    assert len(solutions) == 1
    facts = solutions[0]["direction"]
    assert P(name=Symbol("n")) in facts
    assert P(name=Symbol("s")) in facts
