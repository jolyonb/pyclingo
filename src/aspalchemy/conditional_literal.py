from aspalchemy.conditioned_element import ConditionedElement, ConditionType, carries_aggregate_comparison
from aspalchemy.core import Comparison, DefaultNegation, PredicateOccurrence, RenderingContext, Term
from aspalchemy.predicate import Predicate


class ConditionalLiteral(Term):
    """
    Represents a conditional literal in ASP programs (head : condition).

    This corresponds to structures like "p(X) : q(X)" in ASP, which
    represent a conjunction over all matches in rule bodies.

    An intuition that helps: think of the head as a "key" and the condition
    as a "lock" — the literal holds when every lock has a matching key.
    Keys without locks are fine; a lock without a key fails. E.g. in a rule
    body, "covered(X) : cell(X)" holds only if every cell is covered.
    """

    def __init__(
        self,
        head: ConditionType,
        condition: ConditionType | list[ConditionType],
    ):
        """
        Initialize a conditional literal.

        Args:
            head: The term that must be satisfied for all matching instances
            condition: The condition(s) that define when the head is required
        """
        if not isinstance(head, (Predicate, Comparison, DefaultNegation)):
            raise TypeError("The head of a conditional literal must be a predicate, comparison, or negated term")
        if carries_aggregate_comparison(head):
            # The same rejection ConditionedElement raises for conditions
            raise ValueError(
                "Aggregates cannot appear inside conditional literal heads (clingo "
                "syntax error); compute the aggregate in a separate rule"
            )
        if condition is None or (isinstance(condition, list) and not condition):
            # A conditionless conditional literal renders as a plain positive
            # literal with entirely different (binding) semantics — reject the
            # category error rather than analyze it wrongly
            raise ValueError(
                "A conditional literal needs at least one condition; for an unconditional literal, use the term itself"
            )

        self._element = ConditionedElement((head,), condition, "conditional literal")

    @property
    def head(self) -> ConditionType:
        """Gets the head term of the conditional literal."""
        head = self._element.targets[0]
        assert isinstance(head, (Predicate, Comparison, DefaultNegation))
        return head

    @property
    def condition(self) -> list[ConditionType]:
        """Gets the conditions of the conditional literal (a defensive copy)."""
        return self._element.conditions

    @property
    def is_grounded(self) -> bool:
        """A conditional literal is grounded if the head and all conditions are grounded."""
        return self._element.is_grounded

    def freeze(self) -> None:
        self._element.freeze()

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        return self._element.render()

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.render()!r})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Conditional literals are body-only (disjunctive heads are unsupported): raises in heads."""
        if is_in_head:
            raise ValueError(
                "Conditional literals cannot be used in rule heads — aspalchemy does not "
                "model disjunctive heads. A Choice with at_least(1) covers most uses, "
                "raw_asp() the rest."
            )

    def collect_defined_constants(self) -> set[str]:
        return self._element.collect_defined_constants()

    def collect_variables(self) -> set[str]:
        return self._element.collect_variables()

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        return self._element.collect_predicate_occurrences(as_argument=as_argument)
