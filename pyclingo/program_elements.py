from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING

from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.core import Term

if TYPE_CHECKING:
    from pyclingo.predicate import PREDICATE_CLASS_TYPE


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
        if not isinstance(text, str):
            raise TypeError(f"Comment text must be a string, got {type(text).__name__}")
        if "*%" in text:
            raise ValueError("Comment text cannot contain '*%', which terminates ASP block comments")
        self.text = text

    def render(self) -> str:
        """Single-line text renders as a % comment; multi-line text as a %* *% block."""
        return f"%*\n{self.text}\n*%" if "\n" in self.text else f"% {self.text}"


class RawASP(ProgramElement):
    """
    A verbatim block of ASP text: the escape hatch for constructs pyclingo
    does not support.

    Raw text is invisible to the program's tree walkers, so declare any
    predicates the block produces via the predicates argument — that is what
    makes #show directives cover them and lets solutions round-trip into
    typed instances. Undeclared atoms appearing in a model fail solving with
    "Unknown predicate type". Constants registered via define_constant() are
    always emitted, so raw text may use them freely.
    """

    def __init__(self, text: str, predicates: Sequence[PREDICATE_CLASS_TYPE] = ()):
        if not isinstance(text, str):
            raise TypeError(f"RawASP text must be a string, got {type(text).__name__}")
        self.text = text
        self.predicates = tuple(predicates)

    def render(self) -> str:
        return self.text

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        return set(self.predicates)


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
        if head is None and not body:
            # [] slips a None-only check and would render a bare "." (clingo parse error)
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
            # A conditional literal's condition extends through commas, so the
            # separator FOLLOWING a conditional literal must be a semicolon —
            # otherwise the next body literal is absorbed into the condition
            parts = []
            for i, term in enumerate(self.body):
                parts.append(term.render())
                if i < len(self.body) - 1:
                    parts.append("; " if isinstance(term, ConditionalLiteral) else ", ")
            result += "".join(parts)

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
