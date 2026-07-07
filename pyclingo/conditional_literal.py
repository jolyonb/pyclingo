from pyclingo.conditioned_element import ConditionedElement
from pyclingo.core import AtomSign, Comparison, DefaultNegation, RenderingContext, Term
from pyclingo.predicate import Predicate

# Terms that can be used in a conditional literal
type CONDITIONAL_TERM_TYPE = Predicate | Comparison | DefaultNegation


class ConditionalLiteral(Term):
    """
    Represents a conditional literal in ASP programs (head : condition).

    This corresponds to structures like "p(X) : q(X)" in ASP,
    which represent a conjunction over all matches in rule bodies.
    """

    def __init__(
        self,
        head: CONDITIONAL_TERM_TYPE,
        condition: CONDITIONAL_TERM_TYPE | list[CONDITIONAL_TERM_TYPE],
    ):
        """
        Initialize a conditional literal.

        Args:
            head: The term that must be satisfied for all matching instances
            condition: The condition(s) that define when the head is required
        """
        if not isinstance(head, (Predicate, Comparison, DefaultNegation)):
            raise TypeError("The head of a conditional literal must be a predicate, comparison, or negated term")

        self._element = ConditionedElement((head,), condition, "conditional literal")

    @property
    def head(self) -> CONDITIONAL_TERM_TYPE:
        """Gets the head term of the conditional literal."""
        head = self._element.targets[0]
        assert isinstance(head, (Predicate, Comparison, DefaultNegation))
        return head

    @property
    def condition(self) -> list[CONDITIONAL_TERM_TYPE]:
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
            raise ValueError("Conditional literals cannot be used in rule heads")

    def collect_defined_constants(self) -> set[str]:
        return self._element.collect_defined_constants()

    def collect_variables(self) -> set[str]:
        return self._element.collect_variables()

    def collect_predicate_signs(self) -> set[AtomSign]:
        return self._element.collect_predicate_signs()


def key_for_each_lock(
    key: CONDITIONAL_TERM_TYPE,
    lock: CONDITIONAL_TERM_TYPE | list[CONDITIONAL_TERM_TYPE],
) -> ConditionalLiteral:
    """
    Ensures there is a matching key for each lock that exists.

    In ASP conditionals (X : Y), this creates a term ensuring that for every
    instance satisfying the lock condition, there must also be a matching key.

    Args:
        key: The term that must be satisfied (the "key")
        lock: The condition(s) defining when the key is required (the "lock")

    Note:
        - Every "lock" must have a matching "key"
        - It's acceptable to have "keys" without corresponding "locks"
    """
    # The wrapper just translates our intuitive lock/key terminology
    # to the standard Clingo terminology used internally
    return ConditionalLiteral(head=key, condition=lock)
