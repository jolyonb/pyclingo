"""
Tests for equality, hashing, and value-caching semantics.

The DSL overloads == on Values/Expressions/Aggregates to build ASP Comparison terms
(SQLAlchemy-style). These tests pin down the hardening around that design:
- Comparisons refuse boolean coercion (no silent `if x == y:` bugs)
- Equal Values are cached as shared objects, so identity hashing gives value semantics
- Predicates have ordinary value equality/hashing (they are data, not DSL terms)
"""

import pytest

from pyclingo import Predicate, Variable
from pyclingo.value import Constant, StringConstant, SymbolicConstant


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
            if Constant(1) == Constant(2):
                pass


class TestValueCaching:
    def test_variables_are_cached(self) -> None:
        assert Variable("X") is Variable("X")
        assert Variable("X") is not Variable("Y")

    def test_constants_are_cached(self) -> None:
        assert Constant(1) is Constant(1)
        assert Constant(1) is not Constant(2)
        assert StringConstant("a") is StringConstant("a")
        assert SymbolicConstant("foo") is SymbolicConstant("foo")

    def test_caching_distinguishes_classes_and_types(self) -> None:
        # str "1" vs int 1, and bool True vs int 1 (True == 1 in Python)
        assert StringConstant("1") is not Constant(1)
        assert Constant(True) is not Constant(1)

    def test_values_are_hashable_with_set_semantics(self) -> None:
        assert len({Variable("X"), Variable("X"), Variable("Y")}) == 2
        assert len({Constant(1), Constant(1), Constant(2)}) == 2
        d = {Variable("X"): "first"}
        d[Variable("X")] = "second"
        assert d == {Variable("X"): "second"}

    def test_invalid_construction_still_raises_cleanly(self) -> None:
        with pytest.raises(TypeError):
            Constant([1, 2])  # type: ignore[arg-type]  # unhashable and invalid
        with pytest.raises(ValueError):
            Variable("lowercase")


class TestPredicateEquality:
    def test_equal_predicates(self) -> None:
        Person = Predicate.define("person", ["name", "age"])
        assert Person(name="alice", age=1) == Person(name="alice", age=1)

    def test_unequal_predicates(self) -> None:
        Person = Predicate.define("person", ["name", "age"])
        assert Person(name="alice", age=1) != Person(name="bob", age=99)
        assert not (Person(name="alice", age=1) == Person(name="alice", age=2))

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

    def test_variable_on_left_still_builds_comparison(self) -> None:
        # Predicate.__eq__ returns NotImplemented for non-predicates; the Variable side
        # takes over and (correctly) rejects a predicate operand.
        X = Variable("X")
        P = Predicate.define("p", ["x"])
        with pytest.raises(ValueError, match="Cannot compare"):
            _ = X == P(x=1)
