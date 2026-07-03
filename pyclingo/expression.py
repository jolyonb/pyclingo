from __future__ import annotations

from typing import TYPE_CHECKING, Union

from pyclingo.comparison_mixin import ComparisonMixin
from pyclingo.operators import (
    BINARY_OPERATIONS,
    NONCOMMUTATIVE_OPERATIONS,
    PRECEDENCE,
    UNARY_OPERATIONS,
    ComparisonOperator,
    Operation,
)
from pyclingo.pool import Pool
from pyclingo.term import RenderingContext, Term
from pyclingo.value import Number, String, Value, Variable

if TYPE_CHECKING:
    from pyclingo.types import (
        COMPARISON_TERM_TYPE,
        EXPRESSION_FIELD_TYPE,
        PREDICATE_CLASS_TYPE,
        VALUE_EXPRESSION_TYPE,
    )


class Expression(Term, ComparisonMixin):
    """
    Represents a mathematical expression in an ASP program.

    Expressions can be binary operations (e.g., X+Y, X*Z) or
    unary operations (e.g., -X).
    """

    def __init__(
        self,
        first_term: EXPRESSION_FIELD_TYPE | None,
        operator: Operation,
        second_term: EXPRESSION_FIELD_TYPE,
    ):
        """first_term is None for unary operations; int operands are coerced to Number."""
        if first_term is not None and not isinstance(first_term, (int, Value, Expression)):
            raise TypeError(f"first_term must be a Value or Expression, got {type(first_term).__name__}")
        if not isinstance(second_term, (int, Value, Expression)):
            raise TypeError(f"second_term must be a Value or Expression, got {type(second_term).__name__}")

        if first_term is None and operator not in UNARY_OPERATIONS:
            raise ValueError(f"Unsupported unary operator: {operator}")
        elif first_term is not None and operator not in BINARY_OPERATIONS:
            raise ValueError(f"Unsupported binary operator: {operator}")

        # Convert Python literals to ASP values
        self._first_term = None if first_term is None else self._convert_if_needed(first_term)
        self._operator = operator
        self._second_term = self._convert_if_needed(second_term)

    @staticmethod
    def _convert_if_needed(value: EXPRESSION_FIELD_TYPE) -> VALUE_EXPRESSION_TYPE:
        """Coerces Python ints to Number; Values and Expressions pass through."""
        if isinstance(value, (Value, Expression)):
            return value

        if isinstance(value, int):
            from pyclingo.value import Number

            return Number(value)

        raise TypeError(f"Cannot convert {type(value).__name__} to an ASP term")

    @property
    def first_term(self) -> VALUE_EXPRESSION_TYPE | None:
        """The left term; None for unary operations."""
        return self._first_term

    @property
    def operator(self) -> Operation:
        return self._operator

    @property
    def second_term(self) -> VALUE_EXPRESSION_TYPE:
        return self._second_term

    @property
    def is_unary(self) -> bool:
        return self._operator in UNARY_OPERATIONS

    @property
    def is_grounded(self) -> bool:
        """An expression is grounded if all its operands are grounded."""
        if self.is_unary:
            return self.second_term.is_grounded
        assert self.first_term is not None
        return self.first_term.is_grounded and self.second_term.is_grounded

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        """
        Renders the expression as a string in Clingo syntax.

        Each expression renders itself with knowledge of how it sits with respect to its parents.
        Expressions should never look at how their children are situated.
        """
        # Handle unary operators first
        if self.operator == Operation.ABS:
            # No parentheses ever needed; absolute value has its own delimiters
            return f"|{self.second_term.render(RenderingContext.DEFAULT)}|"

        if self.operator == Operation.UNARY_MINUS:
            second_str = self.second_term.render(RenderingContext.DEFAULT, self.operator, False)
            expr = f"-{second_str}"
            # Need parentheses when it's inside another operation (abs never passes the operation through)
            needs_outer_parentheses = parent_op is not None
            return f"({expr})" if needs_outer_parentheses else expr

        # Must be a binary operation
        assert self.first_term is not None
        first_str = self.first_term.render(RenderingContext.IN_EXPRESSION, self.operator, False)
        second_str = self.second_term.render(RenderingContext.IN_EXPRESSION, self.operator, True)

        expr = f"{first_str} {self.operator.value} {second_str}"

        # Determine if parentheses are needed
        needs_parentheses = False
        if parent_op is not None:
            current_precedence = PRECEDENCE[self.operator]
            parent_precedence = PRECEDENCE[parent_op]

            if current_precedence < parent_precedence:
                # Current operation has lower precedence than parent - always needs parentheses
                needs_parentheses = True
            elif current_precedence > parent_precedence:
                # Current operation has higher precedence than parent - never needs parentheses
                needs_parentheses = False
            elif current_precedence == parent_precedence:
                # Same precedence - need to handle carefully
                if parent_op in NONCOMMUTATIVE_OPERATIONS:
                    # When we're on the right side of a non-commutative parent operation,
                    # we always need parentheses for an expression at the same precedence.
                    # e.g., a - (b - c)
                    needs_parentheses = is_right_operand

                # Special case: Integer division within multiplication
                # This is to handle the case where (X * Y) // Z is different from X * (Y // Z)
                if self.operator == Operation.INTEGER_DIVIDE and parent_op == Operation.MULTIPLY:
                    # Add parentheses when we're the right side of multiplication
                    # For cases like X * (Y // Z)
                    needs_parentheses = is_right_operand

        # Apply parentheses if needed
        return f"({expr})" if needs_parentheses else expr

    def validate_in_context(self, is_in_head: bool) -> None:
        """Expressions cannot appear standalone in rule heads or bodies: always raises."""
        raise ValueError("Expressions can only be used as parts of comparisons, assignments, or as predicate arguments")

    # Arithmetic operator methods
    def __add__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.ADD, other)

    def __radd__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.ADD, self)

    def __sub__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.SUBTRACT, other)

    def __rsub__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.SUBTRACT, self)

    def __mul__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.MULTIPLY, other)

    def __rmul__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.MULTIPLY, self)

    def __neg__(self) -> Expression:
        return Expression(None, Operation.UNARY_MINUS, self)

    def __floordiv__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.INTEGER_DIVIDE, other)

    def __rfloordiv__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.INTEGER_DIVIDE, self)

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        predicates = set()

        if self.first_term is not None:
            predicates.update(self.first_term.collect_predicates())

        predicates.update(self.second_term.collect_predicates())

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        if self.first_term is not None:
            constants.update(self.first_term.collect_defined_constants())

        constants.update(self.second_term.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables = set()

        if self.first_term is not None:
            variables.update(self.first_term.collect_variables())

        variables.update(self.second_term.collect_variables())

        return variables


class Comparison(Term):
    """
    Represents a comparison between two terms in an ASP program.

    Comparisons can be equality (=), inequality (!=), or
    relational comparisons (<, <=, >, >=).
    """

    _left_term: COMPARISON_TERM_TYPE
    _right_term: COMPARISON_TERM_TYPE | Pool

    def __init__(
        self,
        left_term: Union[int, str, Term],
        operator: ComparisonOperator,
        right_term: Union[int, str, Term],
    ):
        """
        int and str operands are coerced to Number and String.

        A Pool may only appear on the right, compared by equality against a variable.
        """
        from pyclingo.aggregates import Aggregate

        # Convert Python literals to ASP values
        if isinstance(left_term, int):
            self._left_term = Number(left_term)
        elif isinstance(left_term, str):
            self._left_term = String(left_term)
        elif isinstance(left_term, (Value, Expression, Aggregate)):
            self._left_term = left_term
        else:
            raise TypeError(
                f"Left term must be an int, str, Value, Expression or Aggregate, got {type(left_term).__name__}"
            )

        if isinstance(right_term, int):
            self._right_term = Number(right_term)
        elif isinstance(right_term, str):
            self._right_term = String(right_term)
        elif isinstance(right_term, (Value, Expression, Aggregate, Pool)):
            self._right_term = right_term
        else:
            raise TypeError(
                f"Right term must be an int, str, Value, Expression, Aggregate or Pool, got {type(right_term).__name__}"
            )

        if not isinstance(operator, ComparisonOperator):
            raise TypeError(f"Comparison operator must be a ComparisonOperator, got {type(operator).__name__}")
        self._operator = operator

        if isinstance(right_term, Pool) and operator != ComparisonOperator.EQUAL:
            raise ValueError("A pool can only be compared using equality")

        if isinstance(right_term, Pool) and not isinstance(left_term, Variable):
            raise ValueError("A comparison involving a pool must have a variable on the left")

    @property
    def left_term(self) -> COMPARISON_TERM_TYPE:
        return self._left_term

    @property
    def operator(self) -> ComparisonOperator:
        return self._operator

    @property
    def right_term(self) -> COMPARISON_TERM_TYPE | Pool:
        return self._right_term

    def __bool__(self) -> bool:
        """
        Comparisons deliberately have no truth value.

        Operators like == on pyclingo terms build ASP comparison terms rather than
        evaluating anything, so code like `if x == y:` is almost certainly a bug.
        Raising here turns that silent wrongness into a loud error.
        """
        raise TypeError(
            f"A Comparison ({self.render()}) has no boolean value: comparison operators on "
            "pyclingo terms build ASP terms rather than evaluating them. If you meant to "
            "compare Python objects, compare their .render() output or use 'is'."
        )

    @property
    def is_grounded(self) -> bool:
        """A comparison is grounded if both its terms are grounded."""
        return self.left_term.is_grounded and self.right_term.is_grounded

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        left_str = self.left_term.render()
        right_str = self.right_term.render()

        expr = f"{left_str} {self.operator.value} {right_str}"

        return f"({expr})" if context == RenderingContext.NEGATION else expr

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Comparisons are valid in both rule bodies and rule heads: a comparison head
        like `C1 = C2 :- body` means the body forces the equality to hold.
        """
        pass

    @property
    def is_assignment(self) -> bool:
        """Whether this comparison assigns a variable: Variable = value."""
        return self.operator == ComparisonOperator.EQUAL and isinstance(self.left_term, Variable)

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        predicates = set()

        predicates.update(self.left_term.collect_predicates())
        predicates.update(self.right_term.collect_predicates())

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        constants.update(self.left_term.collect_defined_constants())
        constants.update(self.right_term.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables = set()

        variables.update(self.left_term.collect_variables())
        variables.update(self.right_term.collect_variables())

        return variables


def Abs(term: EXPRESSION_FIELD_TYPE) -> Expression:
    """Builds an absolute-value expression, |term|."""
    return Expression(None, Operation.ABS, term)
