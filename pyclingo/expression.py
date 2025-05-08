from __future__ import annotations

from typing import TYPE_CHECKING, Union

from pyclingo.comparison_mixin import ComparisonMixin
from pyclingo.operators import (
    BINARY_OPERATIONS,
    NONCOMMUTATIVE_OPERATIONRS,
    PRECEDENCE,
    UNARY_OPERATIONS,
    ComparisonOperator,
    Operation,
)
from pyclingo.pool import Pool
from pyclingo.term import Term
from pyclingo.value import Constant, StringConstant, Value, Variable

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
        """
        Initialize an expression.

        Args:
            first_term: The left-hand operand. None for unary operations.
            operator: The operator.
            second_term: The right-hand operand.

        Raises:
            ValueError: If the operator is invalid or incompatible with operands.
            TypeError: If the operands are of invalid types.
        """
        if first_term is not None and not isinstance(first_term, (int, Value, Expression)):
            raise TypeError(f"first_term must be a Value or Expression, got {type(first_term).__name__}")
        if not isinstance(second_term, (int, Value, Expression)):
            raise TypeError(f"second_term must be a Value or Expression, got {type(first_term).__name__}")

        # Validate the expression structure
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
        """
        Converts Python literals to appropriate ASP Value objects.

        Args:
            value: A value that may need conversion.

        Returns:
            A Value or Expression object.

        Raises:
            TypeError: If the value cannot be converted to a valid ASP term.
        """
        if isinstance(value, (Value, Expression)):
            return value

        if isinstance(value, int):
            from pyclingo.value import Constant

            return Constant(value)

        raise TypeError(f"Cannot convert {type(value).__name__} to an ASP term")

    @property
    def first_term(self) -> VALUE_EXPRESSION_TYPE | None:
        """Gets the first (left) term of the expression."""
        return self._first_term

    @property
    def operator(self) -> Operation:
        """Gets the operator of the expression."""
        return self._operator

    @property
    def second_term(self) -> VALUE_EXPRESSION_TYPE:
        """Gets the second (right) term of the expression."""
        return self._second_term

    @property
    def is_unary(self) -> bool:
        """Determines if this is a unary operation."""
        return self._operator in UNARY_OPERATIONS

    @property
    def is_grounded(self) -> bool:
        """
        An expression is grounded if all its operands are grounded.

        Returns:
            bool: True if all operands are grounded, False otherwise.
        """
        if self.is_unary:
            return self.second_term.is_grounded
        assert self.first_term is not None
        return self.first_term.is_grounded and self.second_term.is_grounded

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the expression as a string in Clingo syntax.

        Handles operator precedence to minimize parentheses.

        Args:
            as_argument: Whether this expression is being rendered as an argument.

        Returns:
            str: The string representation of the expression.
        """
        if self.is_unary:
            if self.operator == Operation.UNARY_MINUS:
                second_str = self.second_term.render()

                # Add parentheses if the operand is a binary expression
                if isinstance(self.second_term, Expression) and not self.second_term.is_unary:
                    second_str = f"({second_str})"

                return f"-{second_str}"
            elif self.operator == Operation.ABS:
                return f"|{self.second_term.render(as_argument=True)}|"
            else:
                raise ValueError(f"Unknown operator {self.operator}")

        # For binary operations
        assert self.first_term is not None
        first_str = self._render_term_with_precedence(self.first_term, self.operator)
        second_str = self._render_term_with_precedence(self.second_term, self.operator, is_right=True)

        result = f"{first_str} {self.operator.value} {second_str}"

        return result if as_argument else f"({result})"

    @staticmethod
    def _render_term_with_precedence(term: VALUE_EXPRESSION_TYPE, parent_op: Operation, is_right: bool = False) -> str:
        """
        Renders a term with appropriate parentheses based on precedence.

        Args:
            term: The term to render.
            parent_op: The parent operation.
            is_right: Whether this is the right operand (for non-commutative ops).

        Returns:
            str: The rendered term, with parentheses if needed.
        """
        # Simple terms don't need parentheses
        if not isinstance(term, Expression):
            return term.render()

        term_str = term.render()

        # Unary expressions generally don't need parentheses
        if term.is_unary:
            return term_str

        # Check if parentheses are needed based on precedence
        parent_precedence = PRECEDENCE[parent_op]
        term_precedence = PRECEDENCE[term.operator]
        needs_parens = False
        # Higher precedence means lower numerical value
        if term_precedence > parent_precedence:
            needs_parens = True
        # For same precedence, non-commutative ops need parens on right side
        elif term_precedence == parent_precedence and is_right and parent_op in NONCOMMUTATIVE_OPERATIONRS:
            needs_parens = True

        return f"({term_str})" if needs_parens else term_str

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this expression for use in a specific context.

        Expressions are typically used in comparisons or assignments,
        not directly in rule heads or bodies.

        Args:
            is_in_head: True if validating for head position, False for body position.

        Raises:
            ValueError: When trying to use an expression directly in a rule.
        """
        raise ValueError("Expressions can only be used as parts of comparisons, assignments, or as predicate arguments")

    # Arithmetic operator methods
    def __add__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        """Creates an Expression representing self + other."""
        return Expression(self, Operation.ADD, other)

    def __radd__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        """Creates an Expression representing other + self."""
        return Expression(other, Operation.ADD, self)

    def __sub__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        """Creates an Expression representing self - other."""
        return Expression(self, Operation.SUBTRACT, other)

    def __rsub__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        """Creates an Expression representing other - self."""
        return Expression(other, Operation.SUBTRACT, self)

    def __mul__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        """Creates an Expression representing self * other."""
        return Expression(self, Operation.MULTIPLY, other)

    def __rmul__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        """Creates an Expression representing other * self."""
        return Expression(other, Operation.MULTIPLY, self)

    def __neg__(self) -> Expression:
        """Creates an Expression representing -self."""
        return Expression(None, Operation.UNARY_MINUS, self)

    def __floordiv__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        """Creates an Expression representing self // other."""
        return Expression(self, Operation.INTEGER_DIVIDE, other)

    def __rfloordiv__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        """Creates an Expression representing other // self."""
        return Expression(other, Operation.INTEGER_DIVIDE, self)

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this expression.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used in this expression.
        """
        predicates = set()

        # Collect from first term if it exists (not the case for unary operations)
        if self.first_term is not None:
            predicates.update(self.first_term.collect_predicates())

        # Collect from second term
        predicates.update(self.second_term.collect_predicates())

        return predicates

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this expression.

        Returns:
            set[str]: A set of symbolic constant names used in this expression.
        """
        constants = set()

        # Collect from first term if it exists (not the case for unary operations)
        if self.first_term is not None:
            constants.update(self.first_term.collect_symbolic_constants())

        # Collect from second term
        constants.update(self.second_term.collect_symbolic_constants())

        return constants

    def collect_variables(self) -> set[str]:
        """
        Collects all variables used in this expression.

        Returns:
            set[str]: A set of variables used in this expression.
        """
        variables = set()

        # Collect from first term if it exists (not the case for unary operations)
        if self.first_term is not None:
            variables.update(self.first_term.collect_variables())

        # Collect from second term
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
        Initialize a comparison.

        Args:
            left_term: The left-hand term.
            operator: The comparison operator.
            right_term: The right-hand term.

        Raises:
            ValueError: If the terms cannot be compared with the given operator.
            TypeError: If the terms are of invalid types.
        """
        from pyclingo.aggregates import Aggregate

        # Convert Python literals to ASP values
        if isinstance(left_term, int):
            self._left_term = Constant(left_term)
        elif isinstance(left_term, str):
            self._left_term = StringConstant(left_term)
        elif isinstance(left_term, (Value, Expression, Aggregate)):
            self._left_term = left_term
        else:
            raise TypeError(
                f"Left term must be an int, str, Value, Expression or Aggregate, got {type(left_term).__name__}"
            )

        if isinstance(right_term, int):
            self._right_term = Constant(right_term)
        elif isinstance(right_term, str):
            self._right_term = StringConstant(right_term)
        elif isinstance(right_term, (Value, Expression, Aggregate, Pool)):
            self._right_term = right_term
        else:
            raise TypeError(
                f"Right term must be an int, str, Value, Expression, Aggregate or Pool, got {type(right_term).__name__}"
            )

        if not isinstance(operator, ComparisonOperator):
            raise TypeError(f"Comparison operator must be a ComparisonOperator, got {type(left_term).__name__}")
        self._operator = operator

        if isinstance(right_term, Pool) and operator != ComparisonOperator.EQUAL:
            raise ValueError("A pool can only be compared using equality")

        if isinstance(right_term, Pool) and not isinstance(left_term, Variable):
            raise ValueError("A comparison involving a pool must have a variable on the left")

    @property
    def left_term(self) -> COMPARISON_TERM_TYPE:
        """Gets the left term of the comparison."""
        return self._left_term

    @property
    def operator(self) -> ComparisonOperator:
        """Gets the operator of the comparison."""
        return self._operator

    @property
    def right_term(self) -> COMPARISON_TERM_TYPE | Pool:
        """Gets the right term of the comparison."""
        return self._right_term

    @property
    def is_grounded(self) -> bool:
        """
        A comparison is grounded if both its terms are grounded.

        Returns:
            bool: True if both terms are grounded, False otherwise.
        """
        return self.left_term.is_grounded and self.right_term.is_grounded

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the comparison as a string in Clingo syntax.

        Args:
            as_argument: Whether this term is being rendered as an argument
                        to another term (e.g., inside a predicate).

        Returns:
            str: The string representation of the comparison.
        """
        left_str = self.left_term.render(as_argument=False)
        right_str = self.right_term.render(as_argument=False)

        return f"{left_str} {self.operator.value} {right_str}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this comparison for use in a specific context.

        Comparisons are valid in rule bodies but not in rule heads.

        Args:
            is_in_head: True if validating for head position, False for body position.

        Raises:
            ValueError: When trying to use a comparison in a rule head.
        """
        pass

    @property
    def is_assignment(self) -> bool:
        """Whether this function represents a variable assignment"""
        return self.operator == ComparisonOperator.EQUAL and isinstance(self.left_term, Variable)

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this comparison.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used in this comparison.
        """
        predicates = set()

        # Collect from left and right terms
        predicates.update(self.left_term.collect_predicates())
        predicates.update(self.right_term.collect_predicates())

        return predicates

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this comparison.

        Returns:
            set[str]: A set of symbolic constant names used in this comparison.
        """
        constants = set()

        # Collect from left and right terms
        constants.update(self.left_term.collect_symbolic_constants())
        constants.update(self.right_term.collect_symbolic_constants())

        return constants

    def collect_variables(self) -> set[str]:
        """
        Collects all variables used in this comparison.

        Returns:
            set[str]: A set of variables used in this comparison.
        """
        variables = set()

        # Collect from left and right terms
        variables.update(self.left_term.collect_variables())
        variables.update(self.right_term.collect_variables())

        return variables


def Abs(term: EXPRESSION_FIELD_TYPE) -> Expression:
    """
    Helper function to use absolute value functions.

    Args:
        term: The term to take the absolute value of.

    Returns:
        Expression: An expression representing the absolute value of the term.
    """
    return Expression(None, Operation.ABS, term)
