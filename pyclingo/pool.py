from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Sequence

from pyclingo.predicate import Predicate
from pyclingo.term import BasicTerm
from pyclingo.value import Constant, ConstantBase

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE, VARIABLE_TYPE
    from pyclingo.expression import Expression


class Pool(BasicTerm, ABC):
    """
    Abstract base class for pools in ASP programs.

    Pools represent collections of terms that can be used as arguments to predicates
    or in other contexts. ASP expands pools differently depending on where they appear:
    conjunctively in heads and disjunctively in bodies.
    """

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this pool for use in a specific position.

        Pools can be used in both heads and bodies, but their
        expansion behavior differs depending on the position.

        Args:
            is_in_head: True if validating for head position, False for body position.
        """
        # Pools can appear in both heads and bodies.
        pass


class RangePool(Pool):
    """
    Represents a range pool in ASP programs, like 1..5.

    Range pools can only contain consecutive integer values or
    symbolic constants that evaluate to a range.
    """

    def __init__(self, start: int | ConstantBase | Expression, end: int | ConstantBase | Expression):
        """
        Initialize a range pool with start and end values.

        Args:
            start: The starting value of the range (inclusive).
            end: The ending value of the range (inclusive).

        Raises:
            TypeError: If start or end is not a ConstantBase.
        """
        from pyclingo.expression import Expression

        # Convert integers to Constant objects
        if isinstance(start, int):
            start = Constant(start)
        if isinstance(end, int):
            end = Constant(end)

        if not isinstance(start, (ConstantBase, Expression)):
            raise TypeError(
                f"Range start must be an int, ConstantBase or Expression, got {type(start).__name__}"
            )
        if isinstance(start, Expression) and not start.is_grounded:
            raise ValueError("Expression in range start must be grounded")

        if not isinstance(end, (ConstantBase, Expression)):
            raise TypeError(
                f"Range end must be an int, ConstantBase or Expression, got {type(end).__name__}"
            )
        if isinstance(end, Expression) and not end.is_grounded:
            raise ValueError("Expression in range end must be grounded")

        self._start: ConstantBase | Expression = start
        self._end: ConstantBase | Expression = end

    @property
    def start(self) -> ConstantBase | Expression:
        """
        Gets the starting value of the range.

        Returns:
            ConstantBase: The starting value.
        """
        return self._start

    @property
    def end(self) -> ConstantBase | Expression:
        """
        Gets the ending value of the range.

        Returns:
            ConstantBase: The ending value.
        """
        return self._end

    @property
    def is_grounded(self) -> bool:
        """
        Ranges are always grounded as they're constructed from constants.
        Since we validate that start and end are ConstantBase objects,
        which are always grounded, this always returns True.

        Returns:
            bool: Always True for range pools.
        """
        return True

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the term as a string in Clingo syntax.

        Args:
            as_argument: Whether this term is being rendered as an argument
                        to another term (e.g., inside a predicate).

        Returns:
            str: The string representation of the range, e.g., "1..5".
        """
        return f"{self.start.render(as_argument=False)}..{self.end.render(as_argument=False)}"

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Range pools don't contain predicates.

        Returns:
            set[type[Predicate]]: An empty set.
        """
        return set()

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this range pool.

        Returns:
            set[str]: A set of symbolic constant names from start and end values.
        """
        constants = set()

        # Collect from start and end values
        constants.update(self.start.collect_symbolic_constants())
        constants.update(self.end.collect_symbolic_constants())

        return constants

    def collect_variables(self) -> set[VARIABLE_TYPE]:
        """
        Range pools don't contain variables.

        Returns:
            set[Variable]: An empty set.
        """
        return set()


class ExplicitPool(Pool):
    """
    Represents an explicit pool in ASP programs, like (1;2;3) or (a;b;c).

    Explicit pools can contain ConstantBase objects or grounded Predicates.
    """

    def __init__(self, elements: Sequence[ConstantBase | Predicate]):
        """
        Initialize an explicit pool with a sequence of elements.

        Args:
            elements: A sequence of ConstantBase objects or grounded Predicates.

        Raises:
            TypeError: If any element is not a ConstantBase or grounded Predicate.
            ValueError: If a Predicate element is not grounded.
        """
        if not elements:
            raise ValueError("ExplicitPool cannot be empty")

        self._elements = []

        for element in elements:
            if not isinstance(element, (ConstantBase, Predicate)):
                raise TypeError(
                    f"Pool element must be a ConstantBase or Predicate, got {type(element).__name__}"
                )

            if isinstance(element, Predicate) and not element.is_grounded:
                raise ValueError(
                    f"Predicate in pool must be grounded: {element.render()}"
                )

            self._elements.append(element)

    @property
    def elements(self) -> list[ConstantBase | Predicate]:
        """
        Gets the elements of the pool.

        Returns:
            list[ConstantBase | Predicate]: The list of elements.
        """
        return self._elements.copy()  # Return a copy to prevent direct modification

    @property
    def is_grounded(self) -> bool:
        """
        Explicit pools are always grounded if constructed properly.

        Since we validate that all elements are either ConstantBase objects
        (which are always grounded) or grounded Predicates, this always returns True.

        Returns:
            bool: Always True for explicit pools.
        """
        return True

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the explicit pool as a string in Clingo syntax.

        Args:
            as_argument: Whether this term is being rendered as an argument
                        to another term (e.g., inside a predicate).

        Returns:
            str: The string representation of the pool, e.g., "1;3;5" or "(1;3;5)".
        """
        elements_str = ";".join(
            element.render(as_argument=True) for element in self._elements
        )

        return elements_str if as_argument else f"({elements_str})"

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this explicit pool.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used in this pool.
        """
        predicates = set()

        for element in self.elements:
            predicates.update(element.collect_predicates())

        return predicates

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this explicit pool.

        Returns:
            set[str]: A set of symbolic constant names used in this pool.
        """
        constants = set()

        for element in self.elements:
            constants.update(element.collect_symbolic_constants())

        return constants

    def collect_variables(self) -> set[VARIABLE_TYPE]:
        """
        Collects all variables used in this explicit pool.

        Returns:
            set[Variable]: A set of variables used in this pool.
        """
        variables = set()

        for element in self.elements:
            variables.update(element.collect_variables())

        return variables
