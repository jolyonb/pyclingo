from abc import ABC
from enum import StrEnum
from typing import ClassVar, Self

from pyclingo.conditioned_element import ConditionedElement, ConditionType, FreezableBuilder
from pyclingo.core import (
    AggregateBase,
    Expression,
    ExtremeConstant,
    PredicateOccurrence,
    RenderingContext,
    String,
    Value,
)
from pyclingo.predicate import Predicate, coerce_tuple_term

type AggregateElementType = int | str | Value | Expression | Predicate


class AggregateType(StrEnum):
    """Enum for the different types of aggregate functions available in ASP."""

    COUNT = "#count"
    SUM = "#sum"
    SUM_PLUS = "#sum+"
    MIN = "#min"
    MAX = "#max"


class Aggregate(FreezableBuilder, AggregateBase, ABC):
    """
    Abstract base class for aggregates in ASP programs.

    Aggregates calculate values over sets of elements, used in expressions like
    #count{ X : p(X) } = 3 or #sum{ W,X : p(X,W) } > 10.

    An aggregate is a mutable builder until a rule captures it, which
    freezes it. A frozen aggregate is a value: build once, use in as many
    rules as you like (capture may be transitive, through a comparison
    holding the aggregate). Only mutation is fenced (it would silently
    rewrite every rule that holds the builder).
    """

    # Set by subclasses to specify which aggregate function to use
    _AGGREGATE_TYPE: ClassVar[AggregateType]

    _RECEIPT_NOUN = "aggregate"

    def __init__(
        self,
        element: AggregateElementType | tuple[AggregateElementType, ...],
        condition: ConditionType | list[ConditionType] | None = None,
    ):
        """
        Create an aggregate with an initial element; see add() for further elements.

        Args:
            element: The value, predicate, or tuple to be aggregated
            condition: Condition(s) determining when the element is included
                      If None, it's an unconditional element
        """
        self._elements: list[ConditionedElement] = []
        self.add(element, condition)

    def add(
        self,
        element: AggregateElementType | tuple[AggregateElementType, ...],
        condition: ConditionType | list[ConditionType] | None = None,
    ) -> Self:
        """
        Add an element with optional condition(s); returns self for chaining.

        Args:
            element: The value, predicate, or tuple to be aggregated
            condition: Condition(s) determining when the element is included
                      If None, it's an unconditional element

        Example:
            >>> from pyclingo import Variable
            >>> X, Y, Z, W = (Variable(n) for n in "XYZW")
            >>> p, q, r = (Predicate.define(name, ["x"]) for name in "pqr")
            >>> Count(X).add(Y, p(x=Y)).add((Z, W), [q(x=Z), r(x=W)]).render()
            '#count{ X; Y : p(Y); Z, W : q(Z), r(W) }'
        """
        self._require_mutable()
        raw_tuple = element if isinstance(element, tuple) else (element,)
        element_tuple = tuple(coerce_tuple_term(item, "Aggregate") for item in raw_tuple)

        # Per-class: #sum/#sum+ SUM the first tuple term, so a literal String
        # (or #sup/#inf) there draws gringo's "tuple ignored" info at ground —
        # weights are integer-valued. Min/Max/Count order terms and take
        # strings (and the ordering's end markers) legally.
        if self._AGGREGATE_TYPE in (AggregateType.SUM, AggregateType.SUM_PLUS):
            if isinstance(element_tuple[0], String):
                raise TypeError(
                    f"{self._AGGREGATE_TYPE.value} weights are integer-valued; the first tuple term "
                    f"{element_tuple[0].render()} is a String, which gringo silently ignores. For "
                    f"term-ordered aggregation over strings use Min/Max, or Count for cardinality."
                )
            if isinstance(element_tuple[0], ExtremeConstant):
                raise TypeError(
                    f"{self._AGGREGATE_TYPE.value} weights are integer-valued, got "
                    f"{element_tuple[0].render()} as the first tuple term."
                )
            if isinstance(element_tuple[0], Predicate):
                raise TypeError(
                    f"{self._AGGREGATE_TYPE.value} weights are integer-valued; the first tuple "
                    f"term {element_tuple[0].render()} is a predicate, which gringo silently "
                    f"ignores (tuple ignored). Lead the tuple with the weight."
                )
        self._elements.append(ConditionedElement(element_tuple, condition, "aggregate"))

        return self

    @property
    def elements(self) -> list[ConditionedElement]:
        """The elements of this aggregate (a defensive copy of the list)."""
        return self._elements.copy()

    @property
    def is_grounded(self) -> bool:
        """
        Grounded means NO variables anywhere, construct-local ones included:
        #count{ X : p(X) } reports False even though X is local in ASP
        semantics — the same strict reading every Term uses.
        """
        return all(element.is_grounded for element in self._elements)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        elements_str = "; ".join(element.render() for element in self._elements)

        return f"{self._AGGREGATE_TYPE.value}{{ {elements_str} }}"

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.render()!r})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Aggregates are only valid inside comparisons: always raises."""
        raise ValueError(
            "Aggregates must be used in comparisons (e.g., #count{ ... } > 0) "
            "and cannot appear directly in rule heads or bodies"
        )

    def collect_defined_constants(self) -> set[str]:
        constants: set[str] = set()

        for element in self._elements:
            constants.update(element.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables: set[str] = set()

        for element in self._elements:
            variables.update(element.collect_variables())

        return variables

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        # Tuple terms sit in argument positions (data); conditions hold real
        # atoms in the aggregate's own position
        occurrences: set[PredicateOccurrence] = set()
        for element in self._elements:
            for target in element.targets:
                occurrences.update(target.collect_predicate_occurrences(as_argument=True))
            for condition in element.conditions:
                occurrences.update(condition.collect_predicate_occurrences(as_argument=as_argument))
        return occurrences


class Count(Aggregate):
    """#count: the number of distinct matching tuples, e.g. #count{ X : p(X) } = 3."""

    _AGGREGATE_TYPE = AggregateType.COUNT


class Sum(Aggregate):
    """
    #sum: the sum of weights over distinct matching tuples, e.g. #sum{ W,X : p(X,W) } > 10.

    The first element in each tuple is the weight.
    """

    _AGGREGATE_TYPE = AggregateType.SUM


class SumPlus(Aggregate):
    """
    #sum+: like Sum, but negative weights are treated as zero.

    The first element in each tuple is the weight.
    """

    _AGGREGATE_TYPE = AggregateType.SUM_PLUS


class Min(Aggregate):
    """
    #min: the minimum value over distinct matching tuples, e.g. #min{ W,X : p(X,W) } < 5.

    The first element in each tuple is the value.
    """

    _AGGREGATE_TYPE = AggregateType.MIN


class Max(Aggregate):
    """
    #max: the maximum value over distinct matching tuples, e.g. #max{ W,X : p(X,W) } < 100.

    The first element in each tuple is the value.
    """

    _AGGREGATE_TYPE = AggregateType.MAX
