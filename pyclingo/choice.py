from __future__ import annotations

from typing import TYPE_CHECKING, Self, Union

from pyclingo.core import Comparison, Number, RenderingContext, String, Term, Value, Variable
from pyclingo.predicate import PREDICATE_CLASS_TYPE, DefaultNegation, Predicate

if TYPE_CHECKING:
    CHOICE_ELEMENT_TYPE = Predicate
    CHOICE_CONDITION_TYPE = Union[Predicate, DefaultNegation, Comparison]
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
        Create a choice rule with an initial element; see add() for further elements.

        Args:
            element: The predicate that can be chosen
            condition: Condition(s) determining when the element is considered
                      If None, it's an unconditional choice
        """
        self._elements: list[tuple[CHOICE_ELEMENT_TYPE, list[CHOICE_CONDITION_TYPE]]] = []
        self._min_cardinality: None | Value = None
        self._max_cardinality: None | Value = None

        self.add(element, condition)

    def add(
        self,
        element: CHOICE_ELEMENT_TYPE,
        condition: Union[CHOICE_CONDITION_TYPE, list[CHOICE_CONDITION_TYPE], None] = None,
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
        if not isinstance(element, Predicate):
            raise TypeError(f"Choice element must be a Predicate, got {type(element).__name__}")

        # Process and validate condition - coerce to list for easier processing
        if condition is None:
            conditions = []
        elif isinstance(condition, list):
            for cond in condition:
                if not isinstance(cond, (Predicate, DefaultNegation, Comparison)):
                    raise TypeError(
                        f"Choice condition must be a Predicate, DefaultNegation, or Comparison, "
                        f"got {type(cond).__name__}"
                    )
            conditions = condition
        elif isinstance(condition, (Predicate, DefaultNegation, Comparison)):
            conditions = [condition]
        else:
            raise TypeError(
                f"Choice condition must be a Predicate, DefaultNegation, Comparison, "
                f"or a list of these, got {type(condition).__name__}"
            )

        self._elements.append((element, conditions))

        return self

    @staticmethod
    def _validate_cardinality(count: Union[int, Value], description: str) -> Value:
        """Validate a cardinality value, coercing ints to Number; raises on bad type or negative int."""
        if not isinstance(count, (int, Value)):
            raise TypeError(f"{description} must be an integer or Value, got {type(count).__name__}")

        # Reject string constants which don't make sense for cardinality
        if isinstance(count, String):
            raise TypeError(f"{description} cannot be a String")

        if isinstance(count, int) and count < 0:
            raise ValueError(f"{description} must be a non-negative integer, got {count}")

        return Number(count) if isinstance(count, int) else count

    def exactly(self, count: CARDINALITY_TYPE) -> Self:
        """
        Set the exact cardinality (min = max = count); returns self for chaining.

        Raises ValueError if cardinality constraints are already set.
        """
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
        count = self._validate_cardinality(count, "Minimum cardinality")

        if self._min_cardinality is not None:
            raise ValueError("Minimum cardinality is already set")

        self._min_cardinality = count

        return self

    def at_most(self, count: CARDINALITY_TYPE) -> Self:
        """
        Set the maximum cardinality; returns self for chaining.

        Raises ValueError if maximum cardinality is already set.
        """
        count = self._validate_cardinality(count, "Maximum cardinality")

        if self._max_cardinality is not None:
            raise ValueError("Maximum cardinality is already set")

        self._max_cardinality = count

        return self

    @property
    def elements(self) -> list[tuple[CHOICE_ELEMENT_TYPE, list[CHOICE_CONDITION_TYPE]]]:
        """The element-condition pairs in this choice rule (a defensive copy)."""
        return self._elements.copy()

    @property
    def min_cardinality(self) -> Union[Value, None]:
        """The minimum cardinality constraint, or None if not set."""
        return self._min_cardinality

    @property
    def max_cardinality(self) -> Union[Value, None]:
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
        for element, conditions in self._elements:
            if not element.is_grounded:
                return False

            for condition in conditions:
                if not condition.is_grounded:
                    return False

        if self.min_cardinality and not self.min_cardinality.is_grounded:
            return False

        if self.max_cardinality and not self.max_cardinality.is_grounded:
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
        """Choice rules are head-only: raises in bodies."""
        if not is_in_head:
            raise ValueError("Choice rules can only be used in rule heads, not in rule bodies")

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        predicates = set()

        for element, conditions in self._elements:
            predicates.update(element.collect_predicates())

            for condition in conditions:
                predicates.update(condition.collect_predicates())

        # Cardinality bounds can never contain predicates

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        for element, conditions in self._elements:
            constants.update(element.collect_defined_constants())

            for condition in conditions:
                constants.update(condition.collect_defined_constants())

        if self.min_cardinality:
            constants.update(self.min_cardinality.collect_defined_constants())

        if self.max_cardinality:
            constants.update(self.max_cardinality.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables = set()

        for element, conditions in self._elements:
            variables.update(element.collect_variables())

            for condition in conditions:
                variables.update(condition.collect_variables())

        if isinstance(self.min_cardinality, Variable):
            variables.add(self.min_cardinality.name)

        if isinstance(self.max_cardinality, Variable):
            variables.add(self.max_cardinality.name)

        return variables
