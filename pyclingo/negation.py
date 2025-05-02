from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Union

from pyclingo.expression import Comparison
from pyclingo.predicate import Predicate
from pyclingo.term import Term

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE, VARIABLE_TYPE


class NegatedLiteral(Term, ABC):
    """
    Abstract base class for negated literals in ASP programs.

    Negated literals are terms prefixed with negation operators:
    either default negation ('not') or classical negation ('-').
    """

    def __init__(self, term: Term):
        """
        Initialize a negated literal with a term to negate.

        Args:
            term: The term to negate.
        """
        self._term = term

    @property
    def term(self) -> Term:
        """
        Gets the term being negated.

        Returns:
            Term: The negated term.
        """
        return self._term

    @property
    def is_grounded(self) -> bool:
        """
        A negated literal is grounded if its term is grounded.

        Returns:
            bool: True if the term is grounded, False otherwise.
        """
        return self._term.is_grounded

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in the negated term.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used in this term.
        """
        return self._term.collect_predicates()

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in the negated term.

        Returns:
            set[str]: A set of symbolic constant names used in this term.
        """
        return self._term.collect_symbolic_constants()

    def collect_variables(self) -> set[VARIABLE_TYPE]:
        """
        Collects all variables used in the negated term.

        Returns:
            set[Variable]: A set of variables used in this term.
        """
        return self._term.collect_variables()


class DefaultNegation(NegatedLiteral):
    """
    Represents default negation ('not') in ASP programs.

    Default negation is used to express that a literal cannot be proven
    to be true (it may be either false or unknown).
    """

    def __init__(self, term: Union[Predicate, Comparison, NegatedLiteral]):
        """
        Initialize a default negation with a term to negate.

        This constructor handles simplification for nested negations.
        For cases like 'not not not p', it simplifies them appropriately:
        - Odd number of negations → equivalent to 'not p'
        - Even number of negations → equivalent to 'not not p'

        Args:
            term: The term to negate.

        Raises:
            TypeError: If the term is not a valid type for default negation.
        """
        # Validate term type
        # TODO: Add Aggregate and ConditionalLiteral when implemented
        if not isinstance(term, (Predicate, Comparison, NegatedLiteral)):
            raise TypeError("Default negation can only be applied to predicates, comparisons, or already negated terms")

        # Handle nested default negations
        if isinstance(term, DefaultNegation):
            inner_term = term.term
            if isinstance(inner_term, DefaultNegation):
                # not not not X -> simplify to not X
                # We're negating the inner term directly
                actual_term = inner_term.term
            else:
                # not not X -> just pass through the original term
                actual_term = term
        else:
            # Normal case: not X
            actual_term = term

        # Initialize with the appropriate term
        super().__init__(actual_term)

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the default negation as a string in Clingo syntax.

        Args:
            as_argument: Whether this term is being rendered as an argument
                        to another term (e.g., inside a predicate).

        Returns:
            str: The string representation of the default negation.
        """
        term_str = self._term.render(as_argument=False)
        return f"not {term_str}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this default negation for use in a specific position.

        Default negation is only allowed in rule bodies, not in rule heads.

        Args:
            is_in_head: True if validating for head position, False for body position.

        Raises:
            ValueError: If trying to use default negation in a rule head.
        """
        if is_in_head:
            raise ValueError("Default negation (not) cannot be used in rule heads")


class ClassicalNegation(NegatedLiteral):
    """
    Represents classical negation ('-') in ASP programs.

    Classical negation is used to express the explicit falsity of a predicate,
    rather than just the absence of proof.
    """

    def __init__(self, term: Union[Predicate, "ClassicalNegation"]):
        """
        Initialize a classical negation with a term to negate.

        This constructor handles simplification for double classical negation:
        -(-p) is simplified to p.

        Args:
            term: The predicate or classical negation to negate.

        Raises:
            TypeError: If the term is not a Predicate or ClassicalNegation.
        """
        if not isinstance(term, (Predicate, ClassicalNegation)):
            raise TypeError("Classical negation can only be applied to predicates or classical negations")

        # Check if we're negating a negation: -(-p) -> simplify to p
        actual_term = term.term if isinstance(term, ClassicalNegation) else term

        # Initialize with the appropriate term
        super().__init__(actual_term)

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the classical negation as a string in Clingo syntax.

        Args:
            as_argument: Whether this term is being rendered as an argument
                        to another term (e.g., inside a predicate).

        Returns:
            str: The string representation of the classical negation.
        """
        term_str = self._term.render(as_argument=as_argument)
        return f"-{term_str}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this classical negation for use in a specific position.

        Classical negation can be used in both rule heads and bodies.

        Args:
            is_in_head: True if validating for head position, False for body position.
        """
        # Classical negation can appear in both heads and bodies
        pass


def Not(term: Union[Predicate, Comparison, NegatedLiteral]) -> DefaultNegation:
    """
    Helper function to create default negation.

    This function applies default negation to the term, with automatic
    simplification of nested negations when appropriate.

    Args:
        term: The term to negate with default negation.

    Returns:
        Term: A default negation of the given term, simplified if needed.

    Example:
        >>> person = Person(name="john")
        >>> not_person = Not(person)  # Renders as: not person(john)
        >>> not_not_person = Not(not_person)  # Renders as: not not person(john)
        >>> not_not_not_person = Not(not_not_person)  # Simplifies to: not person(john)
    """
    return DefaultNegation(term)
