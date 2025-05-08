from __future__ import annotations

from typing import TYPE_CHECKING, Self, Union

from pyclingo.expression import Comparison
from pyclingo.negation import ClassicalNegation, NegatedLiteral
from pyclingo.predicate import Predicate
from pyclingo.term import Term
from pyclingo.value import Constant, StringConstant, Value, Variable

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE

    CHOICE_ELEMENT_TYPE = Union[Predicate, ClassicalNegation]
    CHOICE_CONDITION_TYPE = Union[Predicate, NegatedLiteral, Comparison]
    CARDINALITY_TYPE = Union[int, Value]


class Choice(Term):
    """
    Represents a choice rule in ASP programs.

    Choice rules in ASP allow for specifying sets of atoms from which some
    subset can be chosen to be true, optionally with cardinality constraints.

    Examples in ASP syntax:
    - { p(X) : q(X) }
    - 2 { p(X) : q(X) } 4
    - { p(X) : q(X) } = 3
    """

    def __init__(
        self,
        element: CHOICE_ELEMENT_TYPE,
        condition: Union[CHOICE_CONDITION_TYPE, list[CHOICE_CONDITION_TYPE], None] = None,
    ):
        """
        Initialize a choice rule with a required initial element and optional condition.

        Args:
            element: The predicate, classically negated predicate, or value that can be chosen
            condition: Condition(s) determining when the element is considered
                      If None, it's an unconditional choice

        Raises:
            TypeError: If element or condition is not of the expected type
        """
        # Initialize internal state
        self._elements: list[tuple[CHOICE_ELEMENT_TYPE, list[CHOICE_CONDITION_TYPE]]] = []
        self._min_cardinality: None | Value = None
        self._max_cardinality: None | Value = None

        # Add required initial element
        self.add(element, condition)

    def add(
        self,
        element: CHOICE_ELEMENT_TYPE,
        condition: Union[CHOICE_CONDITION_TYPE, list[CHOICE_CONDITION_TYPE], None] = None,
    ) -> Self:
        """
        Add another element to the choice rule.

        Args:
            element: The predicate, classically negated predicate, or value that can be chosen
            condition: Condition(s) determining when the element is considered
                      If None, it's an unconditional choice

        Returns:
            self: For method chaining

        Example:
            # Create a choice rule with multiple elements
            choice = Choice(p(X)).add(q(X), r(X)).add(s(X), [t(X), u(X)])
            # This produces: { p(X); q(X) : r(X); s(X) : t(X), u(X) }

        Raises:
            TypeError: If element or condition is not of the expected type
        """
        # Validate element
        if not isinstance(element, (Predicate, ClassicalNegation)):
            raise TypeError(
                f"Choice element must be a Predicate, ClassicalNegation, or Value, got {type(element).__name__}"
            )

        # Process and validate condition - coerce to list for easier processing
        if condition is None:
            # Empty list for no conditions
            conditions = []
        elif isinstance(condition, list):
            # Use the list directly
            for cond in condition:
                if not isinstance(cond, (Predicate, NegatedLiteral, Comparison)):
                    raise TypeError(
                        f"Choice condition must be a Predicate, NegatedLiteral, or Comparison, "
                        f"got {type(cond).__name__}"
                    )
            conditions = condition
        elif isinstance(condition, (Predicate, NegatedLiteral, Comparison)):
            # Single condition as a list with one element
            conditions = [condition]
        else:
            raise TypeError(
                f"Choice condition must be a Predicate, NegatedLiteral, Comparison, "
                f"or a list of these, got {type(condition).__name__}"
            )

        # Add element and its conditions to the internal list
        self._elements.append((element, conditions))

        return self

    @staticmethod
    def _validate_cardinality(count: Union[int, Value], description: str) -> Value:
        """
        Validate and process a cardinality value, converting it to a Value if needed.

        Args:
            count: The cardinality value to validate
            description: Description for error messages

        Returns:
            The validated cardinality value as a Value object

        Raises:
            TypeError: If count is not an int or appropriate Value
            ValueError: If count is a negative int
        """
        # Check type
        if not isinstance(count, (int, Value)):
            raise TypeError(f"{description} must be an integer or Value, got {type(count).__name__}")

        # Reject string constants which don't make sense for cardinality
        if isinstance(count, StringConstant):
            raise TypeError(f"{description} cannot be a StringConstant")

        # Check for negative integers
        if isinstance(count, int) and count < 0:
            raise ValueError(f"{description} must be a non-negative integer, got {count}")

        return Constant(count) if isinstance(count, int) else count

    def exactly(self, count: CARDINALITY_TYPE) -> Self:
        """
        Set the exact cardinality requirement for the choice rule.

        Args:
            count: The exact number of elements that must be chosen

        Returns:
            self: For method chaining

        Raises:
            TypeError: If count is not a positive integer or appropriate Value
            ValueError: If count is a negative integer
            ValueError: If cardinality constraints are already set
        """
        # Validate the cardinality value
        count = self._validate_cardinality(count, "Exact cardinality")

        # Check for existing constraints
        if self._min_cardinality is not None or self._max_cardinality is not None:
            raise ValueError("Cardinality constraints are already set")

        self._min_cardinality = count
        self._max_cardinality = count

        return self

    def at_least(self, count: CARDINALITY_TYPE) -> Self:
        """
        Set the minimum cardinality requirement for the choice rule.

        Args:
            count: The minimum number of elements that must be chosen

        Returns:
            self: For method chaining

        Raises:
            TypeError: If count is not an integer or appropriate Value
            ValueError: If count is a negative integer
            ValueError: If minimum cardinality is already set
        """
        # Validate the cardinality value
        count = self._validate_cardinality(count, "Minimum cardinality")

        # Check for existing min constraint
        if self._min_cardinality is not None:
            raise ValueError("Minimum cardinality is already set")

        self._min_cardinality = count

        return self

    def at_most(self, count: CARDINALITY_TYPE) -> Self:
        """
        Set the maximum cardinality requirement for the choice rule.

        Args:
            count: The maximum number of elements that can be chosen

        Returns:
            self: For method chaining

        Raises:
            TypeError: If count is not an integer or appropriate Value
            ValueError: If count is a negative integer
            ValueError: If maximum cardinality is already set
        """
        # Validate the cardinality value
        count = self._validate_cardinality(count, "Maximum cardinality")

        # Check for existing max constraint
        if self._max_cardinality is not None:
            raise ValueError("Maximum cardinality is already set")

        self._max_cardinality = count

        return self

    @property
    def elements(self) -> list[tuple[CHOICE_ELEMENT_TYPE, list[CHOICE_CONDITION_TYPE]]]:
        """
        Get the list of element-condition pairs in this choice rule.

        Returns:
            List of tuples, each containing an element and its list of conditions
        """
        return self._elements.copy()  # Return a copy to prevent direct modification

    @property
    def min_cardinality(self) -> Union[Value, None]:
        """
        Get the minimum cardinality constraint, or None if not set.

        Returns:
            The minimum number of elements that must be chosen, or None
        """
        return self._min_cardinality

    @property
    def max_cardinality(self) -> Union[Value, None]:
        """
        Get the maximum cardinality constraint, or None if not set.

        Returns:
            The maximum number of elements that can be chosen, or None
        """
        return self._max_cardinality

    @property
    def is_grounded(self) -> bool:
        """
        A Choice rule is grounded if all its elements and conditions are grounded.

        Note: This property strictly checks all variables, including those that would be
        considered "local" to the aggregate in ASP semantics. For example, in
        {X : p(X)}, the variable X is local to the aggregate but this property
        will still report False because X is ungrounded. This approach ensures
        consistency with how other Term classes handle groundedness.
        We may later add a separate property to check that no global variables are used if needed.

        Returns:
            bool: True if everything is grounded, False otherwise.
        """
        for element, conditions in self._elements:
            if not element.is_grounded:
                return False

            for condition in conditions:
                if not condition.is_grounded:
                    return False

        # Check if cardinality bounds are grounded
        if self.min_cardinality and not self.min_cardinality.is_grounded:
            return False

        if self.max_cardinality and not self.max_cardinality.is_grounded:
            return False

        return True

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the choice rule as a string in Clingo syntax.

        Args:
            as_argument: Whether this term is being rendered as an argument
                        (not typically relevant for choice rules).

        Returns:
            str: The string representation of the choice rule in Clingo syntax.
        """
        # Render the cardinality constraints
        prefix = ""
        suffix = ""

        if self.min_cardinality and self.max_cardinality:
            min_str = self.min_cardinality.render()
            max_str = self.max_cardinality.render()

            if min_str == max_str:
                # Exact cardinality: { ... } = n
                suffix = f" = {min_str}"
            else:
                # Range cardinality: n { ... } m
                prefix = f"{min_str} "
                suffix = f" {max_str}"
        elif self.min_cardinality:
            # Only minimum: n { ... }
            min_str = self.min_cardinality.render()
            prefix = f"{min_str} "
        elif self.max_cardinality:
            # Only maximum: { ... } m
            max_str = self.max_cardinality.render()
            suffix = f" {max_str}"

        # Render the elements with their conditions
        elements_str = []

        for element, conditions in self._elements:
            element_str = element.render()

            if conditions:
                conditions_str = ", ".join(cond.render() for cond in conditions)
                elements_str.append(f"{element_str} : {conditions_str}")
            else:
                elements_str.append(element_str)

        return f"{prefix}{{ {'; '.join(elements_str)} }}{suffix}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this choice rule for use in a specific context.

        Args:
            is_in_head: True if validating for head position, False for body position.

        Raises:
            ValueError: When trying to use a choice rule in a rule body.
        """
        if not is_in_head:
            raise ValueError("Choice rules can only be used in rule heads, not in rule bodies")

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this choice rule.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used in this choice rule.
        """
        predicates = set()

        # Collect from all elements and their conditions
        for element, conditions in self._elements:
            predicates.update(element.collect_predicates())

            for condition in conditions:
                predicates.update(condition.collect_predicates())

        # Cardinality bounds can never contain predicates

        return predicates

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this choice rule.

        Returns:
            set[str]: A set of symbolic constant names used in this choice rule.
        """
        constants = set()

        # Collect from all elements and their conditions
        for element, conditions in self._elements:
            constants.update(element.collect_symbolic_constants())

            for condition in conditions:
                constants.update(condition.collect_symbolic_constants())

        # Check cardinality bounds
        if self.min_cardinality:
            constants.update(self.min_cardinality.collect_symbolic_constants())

        if self.max_cardinality:
            constants.update(self.max_cardinality.collect_symbolic_constants())

        return constants

    def collect_variables(self) -> set[str]:
        """
        Collects all variables used in this choice rule.

        Returns:
            set[str]: A set of variables used in this choice rule.
        """
        variables = set()

        # Collect from all elements and their conditions
        for element, conditions in self._elements:
            variables.update(element.collect_variables())

            for condition in conditions:
                variables.update(condition.collect_variables())

        # Check cardinality bounds
        if isinstance(self.min_cardinality, Variable):
            variables.add(self.min_cardinality.name)

        if isinstance(self.max_cardinality, Variable):
            variables.add(self.max_cardinality.name)

        return variables
