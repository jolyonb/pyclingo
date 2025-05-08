from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from pyclingo.term import Term

if TYPE_CHECKING:
    from pyclingo.expression import Comparison


class ComparisonMixin(ABC):
    """
    Mixin class that provides comparison operator methods.

    This should only be applied to Term subclasses that represent values
    that can be meaningfully compared. This includes:
    * Value
    * Expression
    * Aggregate
    """

    def __lt__(self, other: Any) -> Comparison:
        """Creates a Comparison representing self < other."""
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.LESS_THAN, other)

    def __le__(self, other: Any) -> Comparison:
        """Creates a Comparison representing self <= other."""
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.LESS_EQUAL, other)

    def __gt__(self, other: Any) -> Comparison:
        """Creates a Comparison representing self > other."""
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.GREATER_THAN, other)

    def __ge__(self, other: Any) -> Comparison:
        """Creates a Comparison representing self >= other."""
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.GREATER_EQUAL, other)

    def __eq__(self, other: Any) -> Comparison:  # type: ignore[override]
        """Creates a Comparison representing self == other."""
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.EQUAL, other)

    def __ne__(self, other: Any) -> Comparison:  # type: ignore[override]
        """Creates a Comparison representing self != other."""
        from pyclingo.aggregates import Aggregate
        from pyclingo.expression import Comparison, Expression
        from pyclingo.operators import ComparisonOperator
        from pyclingo.value import Value

        if not isinstance(other, (Expression, Value, Aggregate, int)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        assert isinstance(self, Term)
        return Comparison(self, ComparisonOperator.NOT_EQUAL, other)
