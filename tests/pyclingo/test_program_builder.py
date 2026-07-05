"""
Tests for ASPProgram's construction methods: fact, when, forbid, raw_asp,
define_constant, and the guards on their inputs.
"""

import pytest

from pyclingo import ASPProgram, Choice, Count, Predicate, Variable
from pyclingo.core import RangePool


def test_facts_must_be_grounded() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match=r"grounded.*variable\(s\) X"):
        program.fact(P(x=Variable("X")))


def test_builder_methods_reject_wrong_types() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="must be Predicate or Choice instances, got str"):
        program.fact("p(1).")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="not a string"):
        program.when("p(X)", let=P(x=1))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="raw_asp\\(\\) text must be a string"):
        program.raw_asp(42)  # type: ignore[arg-type]


def test_empty_conditions_are_rejected() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match="forbid\\(\\) requires at least one"):
        program.forbid()
    with pytest.raises(ValueError, match="use fact\\(\\)"):
        program.when([], let=P(x=1))
    with pytest.raises(ValueError, match="use fact\\(\\)"):
        program.when([], let=Choice(P(x=RangePool(1, 3))))


def test_bare_choice_rules_are_facts() -> None:
    # A bare choice rule is an unconditional statement, so fact() states it
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    program.fact(Choice(P(x=RangePool(1, 3))))
    assert "{ p(1..3) }." in program.render()


def test_constant_values_must_fit_clingo_integers() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="outside clingo's integer range"):
        program.define_constant("big", 2**40)


def test_aggregate_comparisons_cannot_be_heads() -> None:
    # clingo rejects these with a misleading "unsafe variables" error
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match="cannot be rule heads"):
        program.when(P(x=1), let=(Count(X, condition=P(x=X)) == 1))
