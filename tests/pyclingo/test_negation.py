"""
Tests for the ~ operator: default negation on predicates and comparisons.
"""

from pyclingo import Not, Predicate, Variable


def test_invert_on_predicates() -> None:
    P = Predicate.define("p", ["x"])
    assert (~P(x=1)).render() == "not p(1)"


def test_invert_on_comparisons() -> None:
    X = Variable("X")
    assert (~(X < 5)).render() == "not (X < 5)"
    assert (~(X == 5)).render() == "not (X = 5)"


def test_invert_nests_and_simplifies_like_not() -> None:
    X = Variable("X")
    assert (~~(X < 5)).render() == "not not (X < 5)"
    assert (~~~(X < 5)).render() == "not (X < 5)"  # triple simplifies
    assert (~(X < 5)).render() == Not(X < 5).render()
