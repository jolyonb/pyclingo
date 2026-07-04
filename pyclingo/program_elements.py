from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pyclingo.core import Term

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE


class ProgramElement(ABC):
    """Base class for any element in an ASP program."""

    @abstractmethod
    def render(self) -> str:
        """Render this element as an ASP string."""
        pass

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """Collects all predicate classes used in this element; the base implementation returns an empty set."""
        return set()

    def collect_defined_constants(self) -> set[str]:
        """Collects all defined constant names used in this element; the base implementation returns an empty set."""
        return set()


class Comment(ProgramElement):
    """Represents a comment in an ASP program."""

    def __init__(self, text: str):
        """text may be multi-line."""
        assert isinstance(text, str)
        self.text = text

    def render(self) -> str:
        """Single-line text renders as a % comment; multi-line text as a %* *% block."""
        return f"%*\n{self.text}\n*%" if "\n" in self.text else f"% {self.text}"


class BlankLine(ProgramElement):
    """Represents a blank line in an ASP program for formatting."""

    def render(self) -> str:
        return ""


class Rule(ProgramElement):
    """Represents an ASP rule."""

    def __init__(self, head: Term | None = None, body: Term | list[Term] | None = None):
        """
        Creates a rule.

        Args:
            head: The head of the rule (None for a constraint)
            body: The body of the rule (None for a fact)

        * Head only: defines a fact
        * Body only: defines a constraint
        * Head and body: defines a rule

        Raises:
            ValueError: If both head and body are None.
        """
        if head is None and body is None:
            raise ValueError("Cannot have a rule with empty head and body!")

        if head is not None:
            head.validate_in_context(is_in_head=True)
        self.head = head

        # Convert body to list and validate
        body_terms = []
        if body is not None:
            body_terms = [body] if isinstance(body, Term) else list(body)
            for term in body_terms:
                term.validate_in_context(is_in_head=False)

        self.body = body_terms

    def render(self) -> str:
        result = ""

        if self.head is not None:
            result += self.head.render()

        if self.body:
            result += " :- " if self.head is not None else ":- "
            result += ", ".join(term.render() for term in self.body)

        result += "."

        return result

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        predicates = set()

        if self.head is not None:
            predicates.update(self.head.collect_predicates())

        for term in self.body:
            predicates.update(term.collect_predicates())

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        if self.head is not None:
            constants.update(self.head.collect_defined_constants())

        for term in self.body:
            constants.update(term.collect_defined_constants())

        return constants

    def collect_variables(self) -> tuple[set[str], set[str]]:
        """Returns (head_vars, body_vars) as separate sets of variable names."""
        head_vars = set()
        body_vars = set()

        if self.head is not None:
            head_vars.update(self.head.collect_variables())

        for term in self.body:
            body_vars.update(term.collect_variables())

        return head_vars, body_vars
