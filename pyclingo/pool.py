from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Sequence, Union

from pyclingo.predicate import Predicate
from pyclingo.term import BasicTerm, RenderingContext
from pyclingo.value import Constant, ConstantBase, StringConstant

if TYPE_CHECKING:
    from pyclingo.expression import Expression
    from pyclingo.types import PREDICATE_CLASS_TYPE


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
            raise TypeError(f"Range start must be an int, ConstantBase or Expression, got {type(start).__name__}")
        if isinstance(start, Expression) and not start.is_grounded:
            raise ValueError("Expression in range start must be grounded")

        if not isinstance(end, (ConstantBase, Expression)):
            raise TypeError(f"Range end must be an int, ConstantBase or Expression, got {type(end).__name__}")
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

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        """
        Renders the term as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The string representation of the range, e.g., "1..5".
        """
        return f"{self.start.render()}..{self.end.render()}"

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

    def collect_variables(self) -> set[str]:
        """
        Range pools don't contain variables.

        Returns:
            set[str]: An empty set.
        """
        return set()


class ExplicitPool(Pool):
    """
    Represents an explicit pool in ASP programs, like (1;2;3) or (a;b;c).

    Explicit pools can contain ConstantBase objects or grounded Predicates.
    """

    def __init__(self, elements: Sequence[int | str | ConstantBase | Predicate]):
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
            if not isinstance(element, (int, str, ConstantBase, Predicate)):
                raise TypeError(
                    f"Pool element must be an int, str, ConstantBase or Predicate, got {type(element).__name__}"
                )

            if isinstance(element, Predicate) and not element.is_grounded:
                raise ValueError(f"Predicate in pool must be grounded: {element.render()}")

            if isinstance(element, str):
                element = StringConstant(element)
            elif isinstance(element, int):
                element = Constant(element)

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

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        """
        Renders the explicit pool as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The string representation of the pool, e.g., "1;3;5" or "(1;3;5)".
        """
        elements_str = "; ".join(element.render() for element in self._elements)
        return elements_str if context == RenderingContext.LONE_PREDICATE_ARGUMENT else f"({elements_str})"

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

    def collect_variables(self) -> set[str]:
        """
        Collects all variables used in this explicit pool.

        Returns:
            set[str]: A set of variables used in this pool.
        """
        variables = set()

        for element in self.elements:
            variables.update(element.collect_variables())

        return variables


def pool(elements: Union[range, Sequence[int | str | ConstantBase | Predicate], Pool]) -> Pool:
    """
    Create a Pool object from a general variety of input options.

    Args:
        elements: A Pool object, range, or sequence of elements
                 (integers, strings, ConstantBase objects, or grounded Predicates)

    Returns:
        An appropriate Pool object (RangePool for continuous ranges, ExplicitPool otherwise)

    Examples:
        >>> pool(range(1, 6))  # Creates a RangePool equivalent to 1..5
        >>> pool([1, 3, 5])    # Creates an ExplicitPool equivalent to (1;3;5)
        >>> pool(["a", "b"])   # Creates an ExplicitPool of string constants

    Raises:
        TypeError: If elements is not a supported type or contains unsupported elements
        ValueError: If attempting to create an empty pool
    """
    pool_elements: Sequence[ConstantBase | Predicate]

    # Handle case where input is already a Pool
    if isinstance(elements, Pool):
        return elements

    elif isinstance(elements, range):
        if elements.step == 1:
            return RangePool(Constant(elements.start), Constant(elements.stop - 1))
        if pool_elements := [Constant(x) for x in elements]:
            return ExplicitPool(pool_elements)
        raise ValueError("Cannot create an empty pool from empty range")

    elif isinstance(elements, (list, tuple)):
        # Check for empty sequence
        if not elements:
            raise ValueError("Cannot create an empty pool")

        # Convert all elements to appropriate types
        pool_elements = []
        for element in elements:
            if isinstance(element, int):
                pool_elements.append(Constant(element))
            elif isinstance(element, str):
                pool_elements.append(StringConstant(element))
            elif isinstance(element, (ConstantBase, Predicate)):
                # Ensure the predicate is grounded
                if isinstance(element, Predicate) and not element.is_grounded:
                    raise ValueError(f"Predicate in pool must be grounded: {element.render()}")
                pool_elements.append(element)
            else:
                raise TypeError(
                    f"Pool element must be an int, str, ConstantBase, or grounded Predicate, "
                    f"got {type(element).__name__}"
                )

        return ExplicitPool(pool_elements)

    else:
        raise TypeError(f"Expected Pool, list, tuple, or range, got {type(elements).__name__}")
