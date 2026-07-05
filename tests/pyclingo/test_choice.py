"""
Tests for Choice construction guards.
"""

import pytest

from pyclingo import Choice, Count, Predicate, Variable


def test_impossible_cardinality_rejected() -> None:
    # Statically impossible bounds would render fine but be silently UNSAT
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match="impossible"):
        Choice(P(x=1)).at_least(3).at_most(2)
    with pytest.raises(ValueError, match="impossible"):
        Choice(P(x=1)).at_most(2).at_least(3)
    Choice(P(x=1)).at_least(2).at_most(3)  # possible bounds fine
    Choice(P(x=1)).at_least(Variable("N")).at_most(2)  # variable bounds skipped


def test_aggregates_rejected_in_conditions() -> None:
    # clingo cannot parse an aggregate inside a choice condition
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="inside choice conditions"):
        Choice(P(x=X), condition=Count(Y, condition=P(x=Y)) > 0)
    with pytest.raises(ValueError, match="inside choice conditions"):
        Choice(P(x=X), condition=[P(x=X), Count(Y, condition=P(x=Y)) > 0])
