from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pyclingo.term import Term

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE, VARIABLE_TYPE


class ProgramElement(ABC):
    """Base class for any element in an ASP program."""

    @abstractmethod
    def render(self) -> str:
        """
        Render this element as an ASP string.

        Returns:
            str: The rendered ASP code for this element.
        """
        pass

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this program element.
        Default implementation returns an empty set.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used in this element.
        """
        return set()

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this program element.
        Default implementation returns an empty set.

        Returns:
            set[str]: A set of symbolic constant names used in this element.
        """
        return set()


class Comment(ProgramElement):
    """Represents a comment in an ASP program."""

    def __init__(self, text: str):
        """
        Initialize a comment with text.

        Args:
            text: The comment text (can be multi-line).
        """
        assert isinstance(text, str)
        self.text = text

    def render(self) -> str:
        """
        Render the comment as ASP syntax.

        Uses single-line comments (%) for single-line text,
        and multi-line comments (%* *%) for multi-line text.

        Returns:
            str: The comment in ASP syntax.
        """
        return f"%*\n{self.text}\n*%" if "\n" in self.text else f"% {self.text}"


class BlankLine(ProgramElement):
    """Represents a blank line in an ASP program for formatting."""

    def render(self) -> str:
        """
        Render a blank line.

        Returns:
            str: An empty string.
        """
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

        # Validate head
        if head is not None:
            head.validate_in_context(is_in_head=True)
        self.head = head

        # Convert body to list and validate
        body_terms = []
        if body is not None:
            body_terms = [body] if isinstance(body, Term) else list(body)
            # Validate each body term
            for term in body_terms:
                term.validate_in_context(is_in_head=False)

        self.body = body_terms

    def render(self) -> str:
        """
        Render as complete ASP rule.

        Returns:
            str: The rendered ASP rule.
        """
        result = ""

        if self.head:
            result += self.head.render()

        if self.body:
            result += " :- " if self.head else ":- "
            result += ", ".join(term.render() for term in self.body)

        result += "."

        return result

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this rule.

        Returns:
            set[type[Predicate]]: A set of predicate classes used in this rule.
        """
        predicates = set()

        # Collect from head if it exists
        if self.head:
            predicates.update(self.head.collect_predicates())

        # Collect from all body terms
        for term in self.body:
            predicates.update(term.collect_predicates())

        return predicates

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this rule.

        Returns:
            set[str]: A set of symbolic constant names used in this rule.
        """
        constants = set()

        # Collect from head if it exists
        if self.head:
            constants.update(self.head.collect_symbolic_constants())

        # Collect from all body terms
        for term in self.body:
            constants.update(term.collect_symbolic_constants())

        return constants

    def collect_variables(self) -> tuple[set[VARIABLE_TYPE], set[VARIABLE_TYPE]]:
        """
        Collects all variables used in this rule.

        Returns:
            tuple[set[Variable], set[Variable]]: Sets of variables used in the head and body.
        """
        head_vars = set()
        body_vars = set()

        # Collect from head if it exists
        if self.head:
            head_vars.update(self.head.collect_variables())

        # Collect from all body terms
        for term in self.body:
            body_vars.update(term.collect_variables())

        return head_vars, body_vars
