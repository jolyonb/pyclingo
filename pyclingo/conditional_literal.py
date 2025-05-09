from __future__ import annotations

from typing import TYPE_CHECKING, Union

from pyclingo.expression import Comparison
from pyclingo.negation import NegatedLiteral
from pyclingo.predicate import Predicate
from pyclingo.term import RenderingContext, Term

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE

    # Type for terms that can be used in a conditional literal
    CONDITIONAL_TERM_TYPE = Union[Predicate, Comparison, NegatedLiteral]


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

        Raises:
            TypeError: If the arguments are not of the correct types
        """
        # Validate head type
        if not isinstance(head, (Predicate, Comparison, NegatedLiteral)):
            raise TypeError("The head of a conditional literal must be a predicate, comparison, or negated term")

        self._head = head

        # Convert single condition to list
        if isinstance(condition, Term):
            self._condition = [condition]
        else:
            self._condition = list(condition)

        # Validate all conditions are valid terms
        for cond in self._condition:
            if not isinstance(cond, (Predicate, Comparison, NegatedLiteral)):
                raise TypeError("Conditions in a conditional literal must be predicates, comparisons, or negated terms")

    @property
    def head(self) -> CONDITIONAL_TERM_TYPE:
        """Gets the head term of the conditional literal."""
        return self._head

    @property
    def condition(self) -> list[CONDITIONAL_TERM_TYPE]:
        """Gets the conditions of the conditional literal."""
        return self._condition.copy()  # Return a copy to prevent modification

    @property
    def is_grounded(self) -> bool:
        """
        A conditional literal is grounded if both the head and all conditions are grounded.

        Returns:
            bool: True if everything is grounded, False otherwise.
        """
        return self.head.is_grounded and all(cond.is_grounded for cond in self.condition)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        """
        Renders the conditional literal as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The string representation of the conditional literal.
        """
        head_str = self.head.render()
        condition_str = ", ".join(cond.render() for cond in self.condition)

        return f"{head_str} : {condition_str}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this conditional literal for use in a specific context.

        Conditional literals are valid in rule bodies but not in rule heads
        (since you're not supporting disjunction).

        Args:
            is_in_head: True if validating for head position, False for body position.

        Raises:
            ValueError: When trying to use a conditional literal in a rule head.
        """
        if is_in_head:
            raise ValueError("Conditional literals cannot be used in rule heads")

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this conditional literal.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used.
        """
        predicates = set()

        # Collect from the head
        predicates.update(self.head.collect_predicates())

        # Collect from all conditions
        for cond in self.condition:
            predicates.update(cond.collect_predicates())

        return predicates

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this conditional literal.

        Returns:
            set[str]: A set of symbolic constant names used.
        """
        constants = set()

        # Collect from key
        constants.update(self.head.collect_symbolic_constants())

        # Collect from all locks
        for cond in self.condition:
            constants.update(cond.collect_symbolic_constants())

        return constants

    def collect_variables(self) -> set[str]:
        """
        Collects all variables used in this conditional literal.

        Returns:
            set[str]: A set of variables used.
        """
        variables = set()

        # Collect from key
        variables.update(self.head.collect_variables())

        # Collect from all locks
        for cond in self.condition:
            variables.update(cond.collect_variables())

        return variables


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
             - Must be a predicate, comparison, or negated term
        lock: The condition defining when the key is required (the "lock")
             - Must be a predicate, comparison, negated term, or list of these

    Returns:
        A conditional literal representing this relationship

    Note:
        - Every "lock" must have a matching "key"
        - It's acceptable to have "keys" without corresponding "locks"
    """
    # The wrapper just translates our intuitive lock/key terminology
    # to the standard Clingo terminology used internally
    return ConditionalLiteral(head=key, condition=lock)
