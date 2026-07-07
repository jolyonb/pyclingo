from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING

from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.core import AtomSign, Term
from pyclingo.scoping import validate_rule

if TYPE_CHECKING:
    from pyclingo.predicate import PREDICATE_CLASS_TYPE


class ProgramElement(ABC):
    """Base class for any element in an ASP program."""

    @abstractmethod
    def render(self) -> str:
        """Render this element as an ASP string."""
        pass

    def collect_defined_constants(self) -> set[str]:
        """Collects all defined constant names used in this element; the base implementation returns an empty set."""
        return set()

    def collect_predicate_signs(self) -> set[AtomSign]:
        """Collects (class, negated, is_atom) occurrences; empty by default."""
        return set()

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """All Predicate classes used in this element (both signs, any position)."""
        return {predicate for predicate, _negated, _is_atom in self.collect_predicate_signs()}


class Comment(ProgramElement):
    """Represents a comment in an ASP program."""

    def __init__(self, text: str):
        """text may be multi-line."""
        if not isinstance(text, str):
            raise TypeError(f"Comment text must be a string, got {type(text).__name__}")
        # Multi-line text renders as a %* *% block, and gringo NESTS block
        # comments: an inner %* swallows the rest of the file, and an inner
        # *% terminates early — both delimiters are forbidden. Single-line
        # text renders after %, where anything goes.
        if "\n" in text and ("%*" in text or "*%" in text):
            raise ValueError("Multi-line comment text cannot contain '%*' or '*%' (ASP block comment delimiters)")
        self.text = text

    def render(self) -> str:
        """Single-line text renders as a % comment; multi-line text as a %* *% block."""
        return f"%*\n{self.text}\n*%" if "\n" in self.text else f"% {self.text}"


class RawASP(ProgramElement):
    """
    A verbatim block of ASP text: the escape hatch for constructs pyclingo
    does not support.

    Raw text is invisible to the program's tree walkers, so the contract is:
    declare EVERY predicate the block produces via predicates=, controlling
    visibility per class (show= at definition, or program show()/hide()) —
    declaration means existence, the show config means visibility, exactly
    as for walked predicates. Declared classes round-trip into typed
    instances and participate in name-collision checks. If a model contains
    an atom whose signature was never declared anywhere, solving fails
    loudly at that model. Constants registered via define_constant() are
    always emitted, so raw text may use them freely.
    """

    def __init__(self, text: str, predicates: Sequence[PREDICATE_CLASS_TYPE] = ()):
        if not isinstance(text, str):
            raise TypeError(f"RawASP text must be a string, got {type(text).__name__}")
        self.text = text
        self.predicates = tuple(predicates)

    def render(self) -> str:
        return self.text

    def collect_predicate_signs(self) -> set[AtomSign]:
        # Declared predicates count as positive atom presence: raw text is
        # invisible to walkers, and predicates= exists to keep #show working
        return {(predicate, False, True) for predicate in self.predicates}


class BlankLine(ProgramElement):
    """Represents a blank line in an ASP program for formatting."""

    def render(self) -> str:
        return ""


class Rule(ProgramElement):
    """Represents an ASP rule."""

    def __init__(self, head: Term | None = None, body: Term | list[Term] | None = None, check_singletons: bool = True):
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

        body_terms = []
        if body is not None:
            body_terms = [body] if isinstance(body, Term) else list(body)
            for term in body_terms:
                term.validate_in_context(is_in_head=False)

        self.body = body_terms

        # Fail fast on unsafe and singleton variables: the traceback lands on
        # the solver author's line, not in clingo's grounding output. The rule
        # itself is passed for error text, rendered only if an error needs it
        validate_rule(self.head, self.body, self, check_singletons=check_singletons)

        # Freeze only now, after ALL validation: a rejected rule must not
        # leave a shared builder locked by a rule that never existed
        if self.head is not None:
            self.head.freeze()
        for term in self.body:
            term.freeze()

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

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        if self.head is not None:
            constants.update(self.head.collect_defined_constants())

        for term in self.body:
            constants.update(term.collect_defined_constants())

        return constants

    def collect_predicate_signs(self) -> set[AtomSign]:
        signs = set() if self.head is None else set(self.head.collect_predicate_signs())
        for term in self.body:
            signs.update(term.collect_predicate_signs())
        return signs
