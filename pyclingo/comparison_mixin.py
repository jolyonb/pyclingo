from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from pyclingo.term import Term

if TYPE_CHECKING:
    from pyclingo.expression import Comparison


class ComparisonMixin(ABC):
    """
    Mixin class that provides comparison operator methods.

    The operators (==, !=, <, <=, >, >=) build Comparison terms rather than
    evaluating anything.

    This should only be applied to Term subclasses that represent values
    that can be meaningfully compared. This includes:
    * Value
    * Expression
    * Aggregate
    """

    # Defining __eq__ sets __hash__ to None; restore identity hashing. This is safe because
    # containers compare stored hash values before calling __eq__, so the ASP-building
    # __eq__ below is never invoked between distinct objects.
    __hash__ = object.__hash__

    def __lt__(self, other: Any) -> Comparison:
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.LESS_THAN, other)

    def __le__(self, other: Any) -> Comparison:
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.LESS_EQUAL, other)

    def __gt__(self, other: Any) -> Comparison:
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.GREATER_THAN, other)

    def __ge__(self, other: Any) -> Comparison:
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.GREATER_EQUAL, other)

    def __eq__(self, other: Any) -> Comparison:  # type: ignore[override]
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.EQUAL, other)

    def __ne__(self, other: Any) -> Comparison:  # type: ignore[override]
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.NOT_EQUAL, other)
