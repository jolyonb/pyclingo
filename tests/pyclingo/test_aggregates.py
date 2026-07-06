"""
Tests for Aggregate construction guards.
"""

import pytest

from pyclingo import ASPProgram, Count, Predicate, Variable


def test_aggregates_rejected_in_aggregate_conditions() -> None:
    # clingo cannot parse a nested aggregate; compute it in a separate rule
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="nested inside aggregate conditions"):
        Count(X, condition=[P(x=X), Count(Y, condition=P(x=Y)) > 0])


def test_aggregate_freezes_when_captured_inside_a_comparison() -> None:
    program = ASPProgram()
    P, Q = Predicate.define("p", ["x"]), Predicate.define("q", ["x"])
    X, Y = Variable("X"), Variable("Y")
    count = Count(X, condition=P(x=X))
    program.when(count == 2, let=Q(x=1))  # aggregate reaches the rule via the Comparison
    with pytest.raises(RuntimeError, match="frozen"):
        count.add(Y, P(x=Y))
