"""
The shared grammar of conditional constructs: "target(s) : conditions".

Choice elements, aggregate elements, and conditional literals behave very
differently — different legal positions, different target types, different
wrappers — but the mechanics of SPECIFYING one element are identical: the
same condition union, the same validation, the same rendering and walking.
ConditionedElement owns those mechanics once; each construct validates its
own targets and renders its own wrapper around the elements it holds.

FreezableBuilder is the other shared piece: the freeze mechanism and its
receipt, common to the mutable builders (Choice, Aggregate) that hold
these elements.
"""

import copy
from typing import ClassVar, Self

from aspalchemy.core import AggregateBase, Comparison, DefaultNegation, PredicateOccurrence, Term
from aspalchemy.predicate import Predicate
from aspalchemy.source_location import SourceLocation, capture_location

# The condition union every conditional construct shares
type ConditionType = Predicate | DefaultNegation | Comparison


class FreezableBuilder:
    """
    The freeze mechanism shared by the mutable builders (Choice, Aggregate): a
    builder mutates freely until a rule captures it. A frozen builder is a
    value — further rules may capture and share it — so only mutation is
    fenced, with the capturing rule's line as the receipt.

    Three ways out of a frozen builder, and they are deliberately different:

    - copy(): a fresh, MUTABLE builder with the same elements. No rule holds
      it, so nothing it does can rewrite a recorded rule. This is what the
      freeze error points at.
    - copy.copy() / copy.deepcopy(): FAITHFUL copies — frozen stays frozen,
      receipt included. ASPProgram.copy() deep-copies a program, and the
      copy's rules still hold their captured builders: unfreezing those would
      hand back a program whose recorded rules could be silently rewritten.
    - Choice bounds (exactly/at_least/at_most): a new bounded Choice, built on
      copy(), so it comes back mutable too.
    """

    # How the mutation error names the builder ("Choice", "aggregate")
    _RECEIPT_NOUN: ClassVar[str]

    # Set by each builder; named here because the copy hooks below must not
    # share the list (a shallow copy that did would let add() on one reach
    # the other)
    _elements: list[ConditionedElement]

    _frozen: bool = False
    _captured_at: SourceLocation | None = None

    def freeze(self) -> None:
        """Fence mutation; the first capture records its authoring line as the mutation error's receipt."""
        if not self._frozen:
            self._frozen = True
            self._captured_at = capture_location()

    def copy(self) -> Self:
        """
        An independent, MUTABLE copy of this builder: same elements, no freeze.

        This is the way out of a frozen builder. The copy is held by no rule,
        so building on it cannot rewrite anything already recorded — which is
        the only thing freezing ever protected.

        What stops add() on one from reaching the other is the fresh element
        LIST (see __copy__, which does only that). Going deep on top of it is
        belt and braces: the ConditionedElements are immutable today, so
        sharing them would be safe, but a copy that owns its own is one fewer
        thing to be careful about later. It stays cheap because the atoms and
        values inside them are immutable and hand themselves back.
        """
        duplicate = copy.deepcopy(self)
        duplicate._frozen = False
        duplicate._captured_at = None
        return duplicate

    def __copy__(self) -> Self:
        """
        A faithful copy: frozen stays frozen, receipt and all.

        Deliberately NOT copy()'s behaviour. A copy that lands inside a copied
        program is still held by that program's rules, and must stay fenced;
        use copy() to get a builder you may keep building.

        Copies the instance __dict__ only: a subclass declaring __slots__ would
        lose that state here, while copy() and deepcopy (which go through
        __reduce_ex__) keep it. No shipped builder has slots, and subclassing
        them is not a supported surface, so this is noted rather than handled.
        """
        duplicate = object.__new__(type(self))
        duplicate.__dict__.update(self.__dict__)
        # A new list, so add() on one cannot reach the other. The
        # ConditionedElements inside ARE shared, which is safe because they are
        # immutable (slots, no setters, conditions returns a defensive copy) —
        # copy(), which deep-copies, does not share them.
        duplicate._elements = list(self._elements)
        return duplicate

    def _require_mutable(self) -> None:
        if self._frozen:
            rule = f"the rule at {self._captured_at.display()}" if self._captured_at is not None else "a rule"
            noun = self._RECEIPT_NOUN
            raise RuntimeError(
                f"This {noun} was captured by {rule} and is frozen; mutating it would "
                f"silently rewrite the recorded rule. Call .copy() for a fresh, mutable "
                f"{noun} with the same elements, or build a new {noun}."
            )


def carries_aggregate_comparison(term: Term) -> bool:
    """
    Whether the term is a comparison with an aggregate side, however deep
    under default negation — the one shape clingo cannot parse in condition
    or conditional-literal-head position.
    """
    inner: Term = term
    while isinstance(inner, DefaultNegation):
        inner = inner.term
    return isinstance(inner, Comparison) and any(
        isinstance(side, AggregateBase) for side in (inner.left_term, inner.right_term)
    )


class ConditionedElement:
    """One "target(s) : conditions" element; immutable once constructed."""

    __slots__ = ("_conditions", "_targets")

    def __init__(
        self,
        targets: tuple[Term, ...],
        condition: ConditionType | list[ConditionType] | None,
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
            if carries_aggregate_comparison(cond):
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
    def conditions(self) -> list[ConditionType]:
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
