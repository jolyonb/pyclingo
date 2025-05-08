from __future__ import annotations

from abc import ABC
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Self, Union

from pyclingo.expression import Comparison, Equals
from pyclingo.negation import NegatedLiteral
from pyclingo.predicate import Predicate
from pyclingo.term import Term
from pyclingo.value import Value, Variable

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE

    AGGREGATE_ELEMENT_TYPE = Union[Value, Predicate]
    AGGREGATE_CONDITION_TYPE = Union[Predicate, NegatedLiteral, Comparison]


class AggregateType(StrEnum):
    """Enum for the different types of aggregate functions available in ASP."""

    COUNT = "#count"
    SUM = "#sum"
    SUM_PLUS = "#sum+"
    MIN = "#min"
    MAX = "#max"


class Aggregate(Term, ABC):
    """
    Abstract base class for aggregates in ASP programs.

    Aggregates calculate values over sets of elements, such as counting, summing,
    finding minimum/maximum values, etc. They are used in expressions like:
    #count{X : p(X)} = 3
    #sum{W,X : p(X,W)} > 10
    """

    # Set by subclasses to specify which aggregate function to use
    AGGREGATE_TYPE: ClassVar[AggregateType]

    def __init__(
        self,
        element: AGGREGATE_ELEMENT_TYPE | tuple[AGGREGATE_ELEMENT_TYPE, ...],
        condition: Union[AGGREGATE_CONDITION_TYPE, list[AGGREGATE_CONDITION_TYPE], None] = None,
    ):
        """
        Initialize an aggregate with an element and optional conditions.

        Args:
            element: The value, predicate, or tuple to be aggregated
            condition: Condition(s) determining when the element is included
                      If None, it's an unconditional element

        Raises:
            TypeError: If element or condition is not of the expected type
        """
        # Initialize internal state
        self._elements: list[tuple[tuple[AGGREGATE_ELEMENT_TYPE, ...], list[AGGREGATE_CONDITION_TYPE]]] = []

        # Add the initial element
        self.add(element, condition)

    def add(
        self,
        element: AGGREGATE_ELEMENT_TYPE | tuple[AGGREGATE_ELEMENT_TYPE, ...],
        condition: Union[AGGREGATE_CONDITION_TYPE, list[AGGREGATE_CONDITION_TYPE], None] = None,
    ) -> Self:
        """
        Add another element to the aggregate.

        Args:
            element: The value, predicate, or tuple to be aggregated
            condition: Condition(s) determining when the element is included
                      If None, it's an unconditional element

        Returns:
            self: For method chaining

        Example:
            # Create a count aggregate with multiple elements
            count = Count(X).add(Y, p(Y)).add((Z, W), [q(Z), r(W)])
            # This produces: #count{X; Y : p(Y); Z,W : q(Z), r(W)}

        Raises:
            TypeError: If element or condition is not of the expected type
        """
        # Process and validate elements
        element_tuple = element if isinstance(element, tuple) else (element,)
        for item in element_tuple:
            if not isinstance(item, (Value, Predicate)):
                raise TypeError(f"Aggregate element items must be Values or Predicates, got {type(item).__name__}")

        # Process and validate conditions
        if condition is None:
            conditions = []
        elif not isinstance(condition, list):
            conditions = [condition]
        else:
            conditions = condition
        for cond in conditions:
            if not isinstance(cond, (Predicate, NegatedLiteral, Comparison)):
                raise TypeError(
                    f"Aggregate condition must be a Predicate, NegatedLiteral, or Comparison, got {type(cond).__name__}"
                )

        self._elements.append((element_tuple, conditions))

        return self

    @property
    def elements(
        self,
    ) -> list[tuple[tuple[AGGREGATE_ELEMENT_TYPE, ...], list[AGGREGATE_CONDITION_TYPE]]]:
        """
        Get the list of element-condition pairs in this aggregate.

        Returns:
            List of tuples, each containing a tuple of elements and a list of conditions
        """
        return self._elements.copy()  # Return a copy to prevent direct modification

    @property
    def is_grounded(self) -> bool:
        """
        An aggregate is grounded if all its elements and conditions are grounded.

        Note: This property strictly checks all variables, including those that would be
        considered "local" to the aggregate in ASP semantics. For example, in
        #count{X : p(X)}, the variable X is local to the aggregate but this property
        will still report False because X is ungrounded. This approach ensures
        consistency with how other Term classes handle groundedness.
        We may later add a separate property to check that no global variables are used if needed.

        Returns:
            bool: True if everything is grounded, False otherwise.
        """
        for element_tuple, conditions in self._elements:
            # Check if all elements in the tuple are grounded
            for element in element_tuple:
                if not element.is_grounded:
                    return False

            # Check if all conditions are grounded
            for condition in conditions:
                if not condition.is_grounded:
                    return False

        return True

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the aggregate as a string in Clingo syntax.

        Args:
            as_argument: Whether this term is being rendered as an argument
                        to another term (e.g., inside a predicate).

        Returns:
            str: The string representation of the aggregate in Clingo syntax.
        """
        # Render the elements with their conditions
        elements_str = []

        for element_tuple, conditions in self._elements:
            element_str = ", ".join(elem.render(as_argument=True) for elem in element_tuple)

            # Add conditions if present
            if conditions:
                conditions_str = ", ".join(cond.render() for cond in conditions)
                elements_str.append(f"{element_str} : {conditions_str}")
            else:
                elements_str.append(element_str)

        # Combine everything into the final aggregate syntax
        return f"{self.AGGREGATE_TYPE.value}{{{'; '.join(elements_str)}}}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this aggregate for use in a specific context.

        Aggregates can only be used as part of comparisons in rule bodies
        or in specific structured contexts. They cannot be directly used
        as rule heads or rule bodies on their own.

        Args:
            is_in_head: True if validating for head position, False for body position.

        Raises:
            ValueError: When trying to use an aggregate directly in a rule.
        """
        raise ValueError(
            "Aggregates must be used in comparisons (e.g., #count{...} > 0) "
            "and cannot appear directly in rule heads or bodies"
        )

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this aggregate.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used in this aggregate.
        """
        predicates = set()

        # Collect from all elements and their conditions
        for element_tuple, conditions in self._elements:
            # Collect from elements
            for element in element_tuple:
                predicates.update(element.collect_predicates())

            # Collect from conditions
            for condition in conditions:
                predicates.update(condition.collect_predicates())

        return predicates

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this aggregate.

        Returns:
            set[str]: A set of symbolic constant names used in this aggregate.
        """
        constants = set()

        # Collect from all elements and their conditions
        for element_tuple, conditions in self._elements:
            # Collect from elements
            for element in element_tuple:
                constants.update(element.collect_symbolic_constants())

            # Collect from conditions
            for condition in conditions:
                constants.update(condition.collect_symbolic_constants())

        return constants

    def collect_variables(self) -> set[str]:
        """
        Collects all variables used in this aggregate.

        Returns:
            set[str]: A set of variables used in this aggregate.
        """
        variables = set()

        # Collect from all elements and their conditions
        for element_tuple, conditions in self._elements:
            # Collect from elements
            for element in element_tuple:
                variables.update(element.collect_variables())

            # Collect from conditions
            for condition in conditions:
                variables.update(condition.collect_variables())

        return variables

    def assign_to(self, variable: Variable) -> Comparison:
        """
        Creates a comparison that assigns this aggregate's value to a variable.

        Args:
            variable: The variable to assign the aggregate result to

        Returns:
            Comparison: A comparison term representing "variable = aggregate"
        """
        if not isinstance(variable, Variable):
            raise TypeError(f"Expected Variable, got {type(variable).__name__}")

        return Equals(variable, self)


class Count(Aggregate):
    """
    Represents a #count aggregate in ASP programs.

    Count aggregates compute the number of distinct tuples that match the conditions.

    Example:
        #count{X : p(X)} = 3
    """

    AGGREGATE_TYPE = AggregateType.COUNT


class Sum(Aggregate):
    """
    Represents a #sum aggregate in ASP programs.

    Sum aggregates compute the sum of weights across all distinct tuples
    that match the conditions. The first element in each tuple is used as the weight.

    Example:
        #sum{W,X : p(X,W)} > 10
    """

    AGGREGATE_TYPE = AggregateType.SUM


class SumPlus(Aggregate):
    """
    Represents a #sum+ aggregate in ASP programs.

    SumPlus aggregates compute the sum of positive weights across all distinct tuples
    that match the conditions. The first element in each tuple is used as the weight.
    Negative weights are treated as zero.

    Example:
        #sum+{W,X : p(X,W)} > 10
    """

    AGGREGATE_TYPE = AggregateType.SUM_PLUS


class Min(Aggregate):
    """
    Represents a #min aggregate in ASP programs.

    Min aggregates compute the minimum value across all distinct tuples
    that match the conditions. The first element in each tuple is used as the value.

    Example:
        #min{W,X : p(X,W)} < 5
    """

    AGGREGATE_TYPE = AggregateType.MIN


class Max(Aggregate):
    """
    Represents a #max aggregate in ASP programs.

    Max aggregates compute the maximum value across all distinct tuples
    that match the conditions. The first element in each tuple is used as the value.

    Example:
        #max{W,X : p(X,W)} < 100
    """

    AGGREGATE_TYPE = AggregateType.MAX
