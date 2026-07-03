from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Union

from pyclingo.expression import Comparison
from pyclingo.predicate import Predicate
from pyclingo.term import RenderingContext, Term

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE


class NegatedLiteral(Term, ABC):
    """
    Abstract base class for negated literals in ASP programs.

    Negated literals are terms prefixed with negation operators:
    either default negation ('not') or classical negation ('-').
    """

    def __init__(self, term: Term):
        self._term = term

    @property
    def term(self) -> Term:
        """The term being negated."""
        return self._term

    @property
    def is_grounded(self) -> bool:
        """A negated literal is grounded if its term is grounded."""
        return self._term.is_grounded

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        return self._term.collect_predicates()

    def collect_defined_constants(self) -> set[str]:
        return self._term.collect_defined_constants()

    def collect_variables(self) -> set[str]:
        return self._term.collect_variables()


class DefaultNegation(NegatedLiteral):
    """
    Represents default negation ('not') in ASP programs.

    Default negation is used to express that a literal cannot be proven
    to be true (it may be either false or unknown).
    """

    def __init__(self, term: Union[Predicate, Comparison, NegatedLiteral]):
        """
        Initialize a default negation, simplifying nested negations:
        an odd number of negations is equivalent to 'not p', an even number to 'not not p'.
        """
        if not isinstance(term, (Predicate, Comparison, NegatedLiteral)):
            raise TypeError("Default negation can only be applied to predicates, comparisons, or already negated terms")

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

        super().__init__(actual_term)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        term_str = self._term.render(context=RenderingContext.NEGATION)
        return f"not {term_str}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Default negation is body-only: raises in heads."""
        if is_in_head:
            raise ValueError("Default negation (not) cannot be used in rule heads")


class ClassicalNegation(NegatedLiteral):
    """
    Represents classical negation ('-') in ASP programs.

    Classical negation is used to express the explicit falsity of a predicate,
    rather than just the absence of proof.
    """

    def __init__(self, term: Union[Predicate, "ClassicalNegation"]):
        """Initialize a classical negation, simplifying double negation: -(-p) becomes p."""
        if not isinstance(term, (Predicate, ClassicalNegation)):
            raise TypeError("Classical negation can only be applied to predicates or classical negations")

        # Check if we're negating a negation: -(-p) -> simplify to p
        actual_term = term.term if isinstance(term, ClassicalNegation) else term

        super().__init__(actual_term)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        term_str = self._term.render()
        return f"-{term_str}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Classical negation is valid in heads and bodies."""
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
        >>> Person = Predicate.define("person", ["name"])
        >>> person = Person(name="john")
        >>> Not(person).render()
        'not person("john")'
        >>> Not(Not(person)).render()
        'not not person("john")'
        >>> Not(Not(Not(person))).render()  # triple negation simplifies
        'not person("john")'
    """
    return DefaultNegation(term)
