from typing import Self

from pyclingo.conditioned_element import CONDITION_TYPE, ConditionedElement
from pyclingo.core import (
    AtomSign,
    Expression,
    Number,
    RenderingContext,
    String,
    Term,
    Value,
)
from pyclingo.predicate import Predicate

type CHOICE_ELEMENT_TYPE = Predicate
type CARDINALITY_TYPE = int | Value | Expression


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
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None = None,
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
        self._frozen = False

        self.add(element, condition)

    def add(
        self,
        element: CHOICE_ELEMENT_TYPE,
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None = None,
    ) -> Self:
        """
        Add another element with optional condition(s); returns self for chaining.

        Args:
            element: The predicate that can be chosen
            condition: Condition(s) determining when the element is considered
                      If None, it's an unconditional choice

        Example:
            >>> from pyclingo import Predicate, Variable
            >>> X = Variable("X")
            >>> p, q, r, s, t, u = (Predicate.define(name, ["x"]) for name in "pqrstu")
            >>> Choice(p(x=X)).add(q(x=X), r(x=X)).add(s(x=X), [t(x=X), u(x=X)]).render()
            '{ p(X); q(X) : r(X); s(X) : t(X), u(X) }'
        """
        self._require_mutable()
        if not isinstance(element, Predicate):
            raise TypeError(f"Choice element must be a Predicate, got {type(element).__name__}")

        self._elements.append(ConditionedElement((element,), condition, "choice"))

        return self

    def _require_mutable(self) -> None:
        if self._frozen:
            raise RuntimeError(
                "This Choice was captured by a rule and is frozen; mutating it would "
                "silently rewrite the recorded rule. Build a new Choice instead."
            )

    def freeze(self) -> None:
        self._frozen = True

    @staticmethod
    def _validate_cardinality(count: int | Value | Expression, description: str) -> Value | Expression:
        """Validate a cardinality value, coercing ints to Number; raises on bad type or negative int."""
        if not isinstance(count, (int, Value, Expression)):
            raise TypeError(f"{description} must be an integer, Value, or Expression, got {type(count).__name__}")

        # Reject string constants which don't make sense for cardinality
        if isinstance(count, String):
            raise TypeError(f"{description} cannot be a String")

        count = Number(count) if isinstance(count, int) else count
        # Checked after coercion so Number(-1) is caught the same as -1
        if isinstance(count, Number) and count.value < 0:
            raise ValueError(f"{description} must be non-negative, got {count.value}")

        return count

    @staticmethod
    def _check_cardinality_possible(minimum: Value | Expression | None, maximum: Value | Expression | None) -> None:
        """Reject statically impossible bounds; renders fine but is silently UNSAT."""
        if isinstance(minimum, Number) and isinstance(maximum, Number) and minimum.value > maximum.value:
            raise ValueError(f"Choice cardinality is impossible: at_least({minimum.value}) > at_most({maximum.value})")

    def exactly(self, count: CARDINALITY_TYPE) -> Self:
        """
        Set the exact cardinality (min = max = count); returns self for chaining.

        Raises ValueError if cardinality constraints are already set.
        """
        self._require_mutable()
        count = self._validate_cardinality(count, "Exact cardinality")

        if self._min_cardinality is not None or self._max_cardinality is not None:
            raise ValueError("Cardinality constraints are already set")

        self._min_cardinality = count
        self._max_cardinality = count

        return self

    def at_least(self, count: CARDINALITY_TYPE) -> Self:
        """
        Set the minimum cardinality; returns self for chaining.

        Raises ValueError if minimum cardinality is already set.
        """
        self._require_mutable()
        count = self._validate_cardinality(count, "Minimum cardinality")

        if self._min_cardinality is not None:
            raise ValueError("Minimum cardinality is already set")
        self._check_cardinality_possible(minimum=count, maximum=self._max_cardinality)

        self._min_cardinality = count

        return self

    def at_most(self, count: CARDINALITY_TYPE) -> Self:
        """
        Set the maximum cardinality; returns self for chaining.

        Raises ValueError if maximum cardinality is already set.
        """
        self._require_mutable()
        count = self._validate_cardinality(count, "Maximum cardinality")

        if self._max_cardinality is not None:
            raise ValueError("Maximum cardinality is already set")
        self._check_cardinality_possible(minimum=self._min_cardinality, maximum=count)

        self._max_cardinality = count

        return self

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
        A Choice rule is grounded if all its elements and conditions are grounded.

        Note: This property strictly checks all variables, including those that would be
        considered "local" to the aggregate in ASP semantics. For example, in
        {X : p(X)}, the variable X is local to the aggregate but this property
        will still report False because X is ungrounded. This approach ensures
        consistency with how other Term classes handle groundedness.
        We may later add a separate property to check that no global variables are used if needed.
        """
        for element in self._elements:
            if not element.is_grounded:
                return False

        if self.min_cardinality and not self.min_cardinality.is_grounded:
            return False

        return not (self.max_cardinality and not self.max_cardinality.is_grounded)

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
        """Choice rules are head-only: raises in bodies."""
        if not is_in_head:
            raise ValueError("Choice rules can only be used in rule heads, not in rule bodies")

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

    def collect_predicate_signs(self) -> set[AtomSign]:
        signs: set[AtomSign] = set()
        for element in self._elements:
            signs.update(element.collect_predicate_signs())
        return signs
