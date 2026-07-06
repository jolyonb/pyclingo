"""
Tests for equality, hashing, and value-caching semantics.

pyclingo overloads == on Values/Expressions/Aggregates to build ASP Comparison terms
(SQLAlchemy-style). These tests pin down the hardening around that design:
- Comparisons refuse boolean coercion (no silent `if x == y:` bugs)
- Equal Values are cached as shared objects, so identity hashing gives value semantics
- Predicates have ordinary value equality/hashing (they are data, not comparison builders)
"""

from typing import cast

import pytest

from pyclingo import Comparison, Predicate, Variable
from pyclingo.core import DefinedConstant, Number, String


class TestComparisonBool:
    def test_equality_comparison_still_renders(self) -> None:
        X = Variable("X")
        assert (X == 5).render() == "X = 5"

    def test_comparison_has_no_truth_value(self) -> None:
        X = Variable("X")
        with pytest.raises(TypeError, match="no boolean value"):
            bool(X == 5)

    def test_if_statement_on_comparison_raises(self) -> None:
        with pytest.raises(TypeError, match="no boolean value"):
            if Number(1) == Number(2):
                pass


class TestValueCaching:
    def test_variables_are_cached(self) -> None:
        assert Variable("X") is Variable("X")
        assert Variable("X") is not Variable("Y")

    def test_constants_are_cached(self) -> None:
        assert Number(1) is Number(1)
        assert Number(1) is not Number(2)
        assert String("a") is String("a")
        assert DefinedConstant("foo") is DefinedConstant("foo")

    def test_caching_distinguishes_classes_and_types(self) -> None:
        assert String("1") is not Number(1)  # str "1" vs int 1

    def test_booleans_are_rejected(self) -> None:
        # bool subclasses int, but a boolean is never a valid ASP term
        with pytest.raises(TypeError, match="got bool"):
            Number(True)

    def test_values_are_hashable_with_set_semantics(self) -> None:
        assert len({Variable("X"), Variable("X"), Variable("Y")}) == 2
        assert len({Number(1), Number(1), Number(2)}) == 2
        d = {Variable("X"): "first"}
        d[Variable("X")] = "second"
        assert d == {Variable("X"): "second"}

    def test_invalid_construction_still_raises_cleanly(self) -> None:
        with pytest.raises(TypeError):
            Number([1, 2])  # type: ignore[arg-type]  # unhashable and invalid
        with pytest.raises(ValueError):
            Variable("lowercase")


class TestPredicateEquality:
    def test_equal_predicates(self) -> None:
        Person = Predicate.define("person", ["name", "age"])
        assert Person(name="alice", age=1) == Person(name="alice", age=1)

    def test_unequal_predicates(self) -> None:
        Person = Predicate.define("person", ["name", "age"])
        assert Person(name="alice", age=1) != Person(name="bob", age=99)
        assert Person(name="alice", age=1) != Person(name="alice", age=2)

    def test_distinct_classes_never_equal(self) -> None:
        A = Predicate.define("thing", ["x"])
        B = Predicate.define("thing", ["x"])
        assert A(x=1) != B(x=1)  # same name, different definitions

    def test_predicates_hashable_with_set_semantics(self) -> None:
        Person = Predicate.define("person", ["name"])
        assert len({Person(name="a"), Person(name="a"), Person(name="b")}) == 2
        assert Person(name="a") in [Person(name="b"), Person(name="a")]
        assert Person(name="c") not in [Person(name="a"), Person(name="b")]

    def test_predicates_as_dict_keys(self) -> None:
        Cell = Predicate.define("cell", ["row", "col"])
        d = {Cell(row=1, col=2): "x"}
        assert d[Cell(row=1, col=2)] == "x"

    def test_nested_predicate_equality(self) -> None:
        Cell = Predicate.define("cell", ["row", "col"])
        Number = Predicate.define("number", ["loc", "value"])
        assert Number(loc=Cell(row=1, col=2), value=5) == Number(loc=Cell(row=1, col=2), value=5)
        assert Number(loc=Cell(row=1, col=2), value=5) != Number(loc=Cell(row=1, col=3), value=5)

    def test_ungrounded_predicate_equality(self) -> None:
        P = Predicate.define("p", ["x"])
        assert P(x=Variable("X")) == P(x=Variable("X"))
        assert P(x=Variable("X")) != P(x=Variable("Y"))

    def test_predicate_vs_variable_builds_comparison(self) -> None:
        # Predicate.__eq__ returns NotImplemented for non-predicates; the Variable
        # side takes over and builds the comparison — written in either order
        X = Variable("X")
        P = Predicate.define("p", ["x"])
        assert (X == P(x=1)).render() == "X = p(1)"
        # Reflection normalizes: Predicate.__eq__ returns NotImplemented, so
        # this is the same Comparison — statically typed bool, hence the cast
        reflected = cast(Comparison, P(x=1) == X)
        assert reflected.render() == "X = p(1)"
