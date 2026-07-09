"""
The shared grammar of conditional constructs: "target(s) : conditions".

Choice elements, aggregate elements, and conditional literals behave very
differently — different legal positions, different target types, different
wrappers — but the mechanics of SPECIFYING one element are identical: the
same condition union, the same validation, the same rendering and walking.
ConditionedElement owns those mechanics once; each construct validates its
own targets and renders its own wrapper around the elements it holds.

FreezableBuilder is the other shared piece: the freeze fence and its
receipt, common to the mutable builders (Choice, Aggregate) that hold
these elements.
"""

from typing import ClassVar

from pyclingo.core import AggregateBase, Comparison, DefaultNegation, PredicateOccurrence, Term
from pyclingo.predicate import Predicate
from pyclingo.source_location import SourceLocation, capture_location

# The condition union every conditional construct shares
type CONDITION_TYPE = Predicate | DefaultNegation | Comparison


class FreezableBuilder:
    """
    The freeze fence shared by the mutable builders (Choice, Aggregate): a
    builder mutates freely until a rule captures it. A frozen builder is a
    value — further rules may capture and share it — so only mutation is
    fenced, with the capturing rule's line as the receipt.
    """

    # How the mutation error names the builder ("Choice", "aggregate")
    _RECEIPT_NOUN: ClassVar[str]

    _frozen: bool = False
    _captured_at: SourceLocation | None = None

    def freeze(self) -> None:
        """Fence mutation; the first capture records its authoring line as the mutation error's receipt."""
        if not self._frozen:
            self._frozen = True
            self._captured_at = capture_location()

    def _require_mutable(self) -> None:
        if self._frozen:
            rule = f"the rule at {self._captured_at.display()}" if self._captured_at is not None else "a rule"
            raise RuntimeError(
                f"This {self._RECEIPT_NOUN} was captured by {rule} and is frozen; mutating it would "
                f"silently rewrite the recorded rule. Build a new {self._RECEIPT_NOUN} instead."
            )


class ConditionedElement:
    """One "target(s) : conditions" element; immutable once constructed."""

    __slots__ = ("_conditions", "_targets")

    def __init__(
        self,
        targets: tuple[Term, ...],
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None,
        construct: str,
    ) -> None:
        """
        The owning construct validates its targets before constructing; this
        validates the conditions. `construct` names the owner in errors
        (e.g. "choice", "aggregate", "conditional literal").
        """
        if condition is None:
            conditions = []
        elif isinstance(condition, list):
            conditions = list(condition)  # copy: the caller's list must not alias rule internals
        else:
            conditions = [condition]

        for cond in conditions:
            if not isinstance(cond, (Predicate, DefaultNegation, Comparison)):
                raise TypeError(
                    f"A {construct} condition must be a Predicate, DefaultNegation, or Comparison, "
                    f"got {type(cond).__name__}"
                )
            inner: Term = cond
            while isinstance(inner, DefaultNegation):
                inner = inner.term
            if isinstance(inner, Comparison) and any(
                isinstance(term, AggregateBase) for term in (inner.left_term, inner.right_term)
            ):
                raise ValueError(
                    f"Aggregates cannot appear inside {construct} conditions (clingo syntax "
                    f"error); compute the aggregate in a separate rule"
                )

        self._targets = targets
        self._conditions = conditions

    @property
    def targets(self) -> tuple[Term, ...]:
        return self._targets

    @property
    def conditions(self) -> list[CONDITION_TYPE]:
        """The element's conditions (a defensive copy)."""
        return self._conditions.copy()

    @property
    def is_grounded(self) -> bool:
        return all(t.is_grounded for t in self._targets) and all(c.is_grounded for c in self._conditions)

    def render(self) -> str:
        targets_str = ", ".join(target.render() for target in self._targets)
        if not self._conditions:
            return targets_str
        conditions_str = ", ".join(cond.render() for cond in self._conditions)
        return f"{targets_str} : {conditions_str}"

    def freeze(self) -> None:
        for target in self._targets:
            target.freeze()
        for cond in self._conditions:
            cond.freeze()

    def collect_variables(self) -> set[str]:
        variables: set[str] = set()
        for target in self._targets:
            variables.update(target.collect_variables())
        for cond in self._conditions:
            variables.update(cond.collect_variables())
        return variables

    def collect_defined_constants(self) -> set[str]:
        constants: set[str] = set()
        for target in self._targets:
            constants.update(target.collect_defined_constants())
        for cond in self._conditions:
            constants.update(cond.collect_defined_constants())
        return constants

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        # Targets (a choice element, a conditional-literal head) and
        # conditions are all in the element's own position: forward as_argument
        occurrences: set[PredicateOccurrence] = set()
        for target in self._targets:
            occurrences.update(target.collect_predicate_occurrences(as_argument=as_argument))
        for cond in self._conditions:
            occurrences.update(cond.collect_predicate_occurrences(as_argument=as_argument))
        return occurrences
