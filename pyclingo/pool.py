from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Sequence, Union

from pyclingo.predicate import Predicate
from pyclingo.term import BasicTerm, RenderingContext
from pyclingo.value import ConstantBase, Number, String

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
        Bare pools are never valid rule elements: always raises. Pools belong
        inside predicates (p(1..5)) or on the right of comparisons (X = 1..5).
        """
        raise ValueError("Pools can only be used as arguments to predicates or in comparisons")


class RangePool(Pool):
    """
    Represents a range pool in ASP programs, like 1..5.

    Range pools can only contain consecutive integer values or
    symbolic constants that evaluate to a range.
    """

    def __init__(self, start: int | ConstantBase | Expression, end: int | ConstantBase | Expression):
        """
        Initialize a range pool with start and end values (both inclusive).

        Raises if either bound is of the wrong type or an ungrounded Expression.
        """
        from pyclingo.expression import Expression

        # Convert integers to Number objects
        if isinstance(start, int):
            start = Number(start)
        if isinstance(end, int):
            end = Number(end)

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
        """The starting value of the range (inclusive)."""
        return self._start

    @property
    def end(self) -> ConstantBase | Expression:
        """The ending value of the range (inclusive)."""
        return self._end

    @property
    def is_grounded(self) -> bool:
        """Always True: bounds are validated to be constants or grounded expressions."""
        return True

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        return f"{self.start.render()}..{self.end.render()}"

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """Range pools cannot contain predicates."""
        return set()

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        constants.update(self.start.collect_defined_constants())
        constants.update(self.end.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        """Range pools cannot contain variables."""
        return set()


class ExplicitPool(Pool):
    """
    Represents an explicit pool in ASP programs, like (1;2;3) or (a;b;c).

    Explicit pools can contain ConstantBase objects or grounded Predicates.
    """

    def __init__(self, elements: Sequence[int | str | ConstantBase | Predicate]):
        """
        Initialize an explicit pool from a non-empty sequence of elements;
        ints and strs are coerced to Number and String.

        Raises if any element is of an unsupported type or an ungrounded Predicate.
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
                element = String(element)
            elif isinstance(element, int):
                element = Number(element)

            self._elements.append(element)

    @property
    def elements(self) -> list[ConstantBase | Predicate]:
        """The elements of the pool (a defensive copy)."""
        return self._elements.copy()

    @property
    def is_grounded(self) -> bool:
        """Always True: elements are validated to be constants or grounded predicates."""
        return True

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        """Renders as e.g. "(1; 3; 5)"; parentheses are dropped as a lone predicate argument."""
        elements_str = "; ".join(element.render() for element in self._elements)
        return elements_str if context == RenderingContext.LONE_PREDICATE_ARGUMENT else f"({elements_str})"

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        predicates = set()

        for element in self.elements:
            predicates.update(element.collect_predicates())

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        for element in self.elements:
            constants.update(element.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
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
        >>> pool(range(1, 6)).render()
        '1..5'
        >>> pool([1, 3, 5]).render()
        '(1; 3; 5)'
        >>> pool(["a", "b"]).render()
        '("a"; "b")'

    Raises:
        TypeError: If elements is not a supported type or contains unsupported elements
        ValueError: If attempting to create an empty pool
    """
    pool_elements: Sequence[ConstantBase | Predicate]

    if isinstance(elements, Pool):
        return elements

    elif isinstance(elements, range):
        if elements.step == 1:
            return RangePool(Number(elements.start), Number(elements.stop - 1))
        if pool_elements := [Number(x) for x in elements]:
            return ExplicitPool(pool_elements)
        raise ValueError("Cannot create an empty pool from empty range")

    elif isinstance(elements, (list, tuple)):
        if not elements:
            raise ValueError("Cannot create an empty pool")

        pool_elements = []
        for element in elements:
            if isinstance(element, int):
                pool_elements.append(Number(element))
            elif isinstance(element, str):
                pool_elements.append(String(element))
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
