from pyclingo.core import AggregateBase, AtomSign, Comparison, DefaultNegation, RenderingContext, Term
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

        self._head = head

        # Convert single condition to list
        if isinstance(condition, Term):
            self._condition = [condition]
        else:
            self._condition = list(condition)

        for cond in self._condition:
            if not isinstance(cond, (Predicate, Comparison, DefaultNegation)):
                raise TypeError("Conditions in a conditional literal must be predicates, comparisons, or negated terms")
            if isinstance(cond, Comparison) and any(
                isinstance(term, AggregateBase) for term in (cond.left_term, cond.right_term)
            ):
                raise ValueError(
                    "Aggregates cannot appear inside conditional literal conditions (clingo "
                    "syntax error); compute the aggregate in a separate rule"
                )

    @property
    def head(self) -> CONDITIONAL_TERM_TYPE:
        """Gets the head term of the conditional literal."""
        return self._head

    @property
    def condition(self) -> list[CONDITIONAL_TERM_TYPE]:
        """Gets the conditions of the conditional literal (a defensive copy)."""
        return self._condition.copy()

    @property
    def is_grounded(self) -> bool:
        """A conditional literal is grounded if the head and all conditions are grounded."""
        return self.head.is_grounded and all(cond.is_grounded for cond in self.condition)

    def freeze(self) -> None:
        self.head.freeze()
        for cond in self._condition:
            cond.freeze()

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        head_str = self.head.render()
        condition_str = ", ".join(cond.render() for cond in self.condition)

        return f"{head_str} : {condition_str}"

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.render()!r})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Conditional literals are body-only (disjunctive heads are unsupported): raises in heads."""
        if is_in_head:
            raise ValueError("Conditional literals cannot be used in rule heads")

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        constants.update(self.head.collect_defined_constants())

        for cond in self.condition:
            constants.update(cond.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables = set()

        variables.update(self.head.collect_variables())

        for cond in self.condition:
            variables.update(cond.collect_variables())

        return variables

    def collect_predicate_signs(self) -> set[AtomSign]:
        signs = set(self.head.collect_predicate_signs())
        for cond in self.condition:
            signs.update(cond.collect_predicate_signs())
        return signs


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
