from typing import Self

from aspalchemy.conditioned_element import ConditionedElement, ConditionType, FreezableBuilder
from aspalchemy.core import (
    Expression,
    ExtremeConstant,
    Number,
    PredicateOccurrence,
    RenderingContext,
    String,
    Term,
    Value,
    Variable,
    negated_literal_value,
)
from aspalchemy.predicate import Predicate

type CardinalityType = int | Value | Expression


class Choice(FreezableBuilder, Term):
    """
    Represents a choice rule in ASP programs.

    Choice rules in ASP allow for specifying sets of atoms from which some
    subset can be chosen to be true, optionally with cardinality constraints.

    Examples in ASP syntax:
    - { p(X) : q(X) }
    - 2 { p(X) : q(X) } 4
    - { p(X) : q(X) } = 3

    A Choice accumulates ELEMENTS by mutation — add() appends to this
    object — and is frozen when a rule captures it, because mutating it
    afterwards would silently rewrite the recorded rule. A frozen Choice is
    still a value: further rules may capture it too, and it renders
    identically in each.

    BOUNDS are different: exactly()/at_least()/at_most() do not mutate, they
    return a new Choice carrying the bound. So one unbounded choice can be
    bounded several ways for several rules — the common shape of "the data
    decides how many" — and bounding a frozen Choice is fine, since nothing
    it holds is rewritten.
    """

    _RECEIPT_NOUN = "Choice"

    def __init__(
        self,
        element: Predicate,
        condition: ConditionType | list[ConditionType] | None = None,
    ):
        """
        Create a choice rule with an initial element; see add() for further elements.

        Args:
            element: The predicate that can be chosen
            condition: Condition(s) determining when the element is considered
                      If None, it's an unconditional choice
        """
        self._elements: list[ConditionedElement] = []
        self._min_cardinality: None | Value | Expression = None
        self._max_cardinality: None | Value | Expression = None

        self.add(element, condition)

    def add(
        self,
        element: Predicate,
        condition: ConditionType | list[ConditionType] | None = None,
    ) -> None:
        """
        Add another element with optional condition(s), in place.

        Args:
            element: The predicate that can be chosen
            condition: Condition(s) determining when the element is considered
                      If None, it's an unconditional choice

        Example:
            >>> from aspalchemy import Predicate, Variable
            >>> X = Variable("X")
            >>> p, q, r, s, t, u = (Predicate.define(name, ["x"]) for name in "pqrstu")
            >>> menu = Choice(p(x=X))
            >>> menu.add(q(x=X), r(x=X))
            >>> menu.add(s(x=X), [t(x=X), u(x=X)])
            >>> menu.render()
            '{ p(X); q(X) : r(X); s(X) : t(X), u(X) }'
        """
        self._require_mutable()
        if not isinstance(element, Predicate):
            raise TypeError(f"Choice element must be a Predicate, got {type(element).__name__}")

        self._elements.append(ConditionedElement((element,), condition, "choice"))

    @staticmethod
    def _validate_cardinality(count: int | Value | Expression, description: str) -> Value | Expression:
        """Validate a cardinality value, coercing ints to Number; raises on bad type or negative int."""
        if not isinstance(count, (int, Value, Expression)):
            raise TypeError(f"{description} must be an integer, Value, or Expression, got {type(count).__name__}")

        # Reject string constants which don't make sense for cardinality
        if isinstance(count, String):
            raise TypeError(f"{description} cannot be a String")
        if isinstance(count, Variable) and count.is_anonymous:
            raise ValueError(
                f"{description} cannot be '_': an anonymous bound binds nothing, and "
                f"gringo rejects the rule as unsafe. Use a named Variable bound in the body."
            )
        if isinstance(count, ExtremeConstant):
            raise TypeError(f"{description} must be integer-valued, got {count.render()}")

        count = Number(count) if isinstance(count, int) else count
        # Checked after coercion so Number(-1) is caught the same as -1;
        # the literal spelling -Number(1) is caught the same way
        if isinstance(count, Number) and count.value < 0:
            raise ValueError(f"{description} must be non-negative, got {count.value}")
        if (folded := negated_literal_value(count)) is not None and folded < 0:
            raise ValueError(f"{description} must be non-negative, got {folded}")

        return count

    @staticmethod
    def _check_cardinality_possible(minimum: Value | Expression | None, maximum: Value | Expression | None) -> None:
        """Reject statically impossible bounds; renders fine but is silently UNSAT."""
        if isinstance(minimum, Number) and isinstance(maximum, Number) and minimum.value > maximum.value:
            raise ValueError(f"Choice cardinality is impossible: at_least({minimum.value}) > at_most({maximum.value})")

    def _bounded(self, minimum: Value | Expression | None, maximum: Value | Expression | None) -> Self:
        """
        A new Choice: these elements, those bounds. The receiver is untouched.

        Bounding is not mutation — it derives a value from a builder — so it
        works on a frozen Choice too, and one unbounded Choice can be bounded
        several ways for several rules. copy() does the work, so a bounded
        Choice comes back mutable and independent, exactly like any other copy.
        """
        duplicate = self.copy()
        duplicate._min_cardinality = minimum
        duplicate._max_cardinality = maximum
        return duplicate

    def exactly(self, count: CardinalityType) -> Self:
        """
        A copy of this Choice with an exact cardinality (min = max = count).

        Returns a NEW Choice; this one is unchanged. That is what lets one
        `menu` be bounded two ways for two rules — the frequent case of a
        choice whose size the data decides — and it is why bounding a frozen
        Choice is allowed: nothing is rewritten.

        Raises ValueError if this Choice already carries cardinality bounds.
        """
        count = self._validate_cardinality(count, "Exact cardinality")

        if self._min_cardinality is not None or self._max_cardinality is not None:
            raise ValueError("Cardinality constraints are already set")

        return self._bounded(count, count)

    def at_least(self, count: CardinalityType) -> Self:
        """
        A copy of this Choice with a minimum cardinality; this one is unchanged.

        Chains: at_least(1).at_most(3) bounds a copy of a copy, and only the
        last one carries both bounds.

        Raises ValueError if this Choice already carries a minimum.
        """
        count = self._validate_cardinality(count, "Minimum cardinality")

        if self._min_cardinality is not None:
            raise ValueError("Minimum cardinality is already set")
        self._check_cardinality_possible(minimum=count, maximum=self._max_cardinality)

        return self._bounded(count, self._max_cardinality)

    def at_most(self, count: CardinalityType) -> Self:
        """
        A copy of this Choice with a maximum cardinality; this one is unchanged.

        Raises ValueError if this Choice already carries a maximum.
        """
        count = self._validate_cardinality(count, "Maximum cardinality")

        if self._max_cardinality is not None:
            raise ValueError("Maximum cardinality is already set")
        self._check_cardinality_possible(minimum=self._min_cardinality, maximum=count)

        return self._bounded(self._min_cardinality, count)

    @property
    def elements(self) -> list[ConditionedElement]:
        """The elements of this choice rule (a defensive copy of the list)."""
        return self._elements.copy()

    @property
    def min_cardinality(self) -> Value | Expression | None:
        """The minimum cardinality constraint, or None if not set."""
        return self._min_cardinality

    @property
    def max_cardinality(self) -> Value | Expression | None:
        """The maximum cardinality constraint, or None if not set."""
        return self._max_cardinality

    @property
    def is_grounded(self) -> bool:
        """
        Grounded means NO variables anywhere, construct-local ones included:
        {X : p(X)} reports False even though X is local in ASP semantics —
        the same strict reading every Term uses.
        """
        for element in self._elements:
            if not element.is_grounded:
                return False

        if self.min_cardinality and not self.min_cardinality.is_grounded:
            return False
        if self.max_cardinality and not self.max_cardinality.is_grounded:  # noqa: SIM103
            return False

        return True

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
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

        elements_str = "; ".join(element.render() for element in self._elements)

        return f"{prefix}{{ {elements_str} }}{suffix}"

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.render()!r})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Choice rules are head-only: raises in bodies, teaching the body spelling."""
        if not is_in_head:
            raise ValueError(
                "A Choice belongs in a rule head, where braces CHOOSE. In a body, "
                "clingo's braces mean a cardinality TEST — a different construct "
                "aspalchemy spells as a Count comparison: Count(X, condition=...) >= n."
            )

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        for element in self._elements:
            constants.update(element.collect_defined_constants())

        if self.min_cardinality:
            constants.update(self.min_cardinality.collect_defined_constants())

        if self.max_cardinality:
            constants.update(self.max_cardinality.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables = set()

        for element in self._elements:
            variables.update(element.collect_variables())

        if self.min_cardinality is not None:
            variables.update(self.min_cardinality.collect_variables())

        if self.max_cardinality is not None:
            variables.update(self.max_cardinality.collect_variables())

        return variables

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        occurrences: set[PredicateOccurrence] = set()
        for element in self._elements:
            occurrences.update(element.collect_predicate_occurrences(as_argument=as_argument))
        return occurrences
