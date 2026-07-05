"""
Tests for Aggregate construction guards.
"""

import pytest

from pyclingo import Count, Predicate, Variable


def test_aggregates_rejected_in_aggregate_conditions() -> None:
    # clingo cannot parse a nested aggregate; compute it in a separate rule
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="nested inside aggregate conditions"):
        Count(X, condition=[P(x=X), Count(Y, condition=P(x=Y)) > 0])
