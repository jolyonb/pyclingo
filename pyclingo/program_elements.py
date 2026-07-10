from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.core import PredicateOccurrence, Term
from pyclingo.predicate import NegatedSignature, Predicate
from pyclingo.scoping import validate_rule
from pyclingo.source_location import SourceLocation

if TYPE_CHECKING:
    from pyclingo.predicate import PredicateClassType


class ProgramElement(ABC):
    """Base class for any element in an ASP program."""

    # Stamped by Segment.append() when location capture is on: the line of
    # user code that authored this element. For a when()-built element whose
    # closer sat on a different line, source_location is the when() site and
    # closed_at is the closer's.
    source_location: SourceLocation | None = None
    closed_at: SourceLocation | None = None

    # Whether this element gets a source location at all; formatting
    # elements (comments, blank lines) opt out — no diagnostic can ever
    # point at them, so stamping would be a wasted stack walk
    locatable: bool = True

    @abstractmethod
    def render(self) -> str:
        """Render this element as an ASP string."""
        pass

    def collect_defined_constants(self) -> set[str]:
        """Collects all defined constant names used in this element; the base implementation returns an empty set."""
        return set()

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        """Collects (class, negated, is_atom) occurrences; empty by default. See Term.collect_predicate_occurrences."""
        return set()

    def collect_predicates(self) -> set[PredicateClassType]:
        """All Predicate classes used in this element (both signs, any position)."""
        return {predicate for predicate, _negated, _is_atom in self.collect_predicate_occurrences(as_argument=False)}


@dataclass(frozen=True)
class RenderedLine:
    """One rendered line of ASP text and the element that produced it (None for program-generated framing)."""

    text: str
    element: ProgramElement | None


class Comment(ProgramElement):
    """Represents a comment in an ASP program."""

    locatable = False

    def __init__(self, text: str):
        """text may be multi-line."""
        if not isinstance(text, str):
            raise TypeError(f"Comment text must be a string, got {type(text).__name__}")
        # A subclass converts to its natural plain str first, so the check
        # below sees exactly the text that will render
        text = str(text)
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


def _scan_asp_text(text: str) -> tuple[str | None, list[tuple[int, int]]]:
    """
    One character-level scan of ASP text, two products: the first
    #program/#include/#external directive (or None), and the [start, end)
    span of every #script block — both judged outside string literals and
    comments. The first two directives restructure the program itself
    (parts, files), which a single-base-part grounding cannot honor;
    #external declares atoms whose truth is set through an API no pyclingo
    verb speaks. Script spans let the annotator keep its notes out of
    embedded source. Block comments NEST in gringo (see Comment), so only
    depth 0 is code; a character scan is required because a line can close
    a comment and resume code, and % may sit inside a string.
    """
    directive: str | None = None
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    depth = 0
    while i < n:
        if depth:
            if text.startswith("%*", i):
                depth += 1
                i += 2
            elif text.startswith("*%", i):
                depth -= 1
                i += 2
            else:
                i += 1
        elif text.startswith("%*", i):
            depth += 1
            i += 2
        elif text[i] == "%":
            # Line comment: code resumes after the newline
            newline = text.find("\n", i)
            if newline == -1:
                break
            i = newline + 1
        elif text[i] == '"':
            # String literal, honoring \" escapes (raw text is arbitrary gringo)
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
        elif text.startswith("#script", i):
            end = text.find("#end.", i)
            if end == -1:
                # Unterminated script: gringo rejects the block itself, and
                # it swallows the rest of the scan either way
                spans.append((i, n))
                break
            spans.append((i, end + len("#end.")))
            i = end + len("#end.")
        elif directive is None and text.startswith("#program", i):
            directive = "#program"
            i += len("#program")
        elif directive is None and text.startswith("#include", i):
            directive = "#include"
            i += len("#include")
        elif directive is None and text.startswith("#external", i):
            directive = "#external"
            i += len("#external")
        else:
            i += 1
    return directive, spans


def _find_unsupported_directive(text: str) -> str | None:
    """The first #program/#include/#external directive outside strings, comments, and #script blocks — or None."""
    return _scan_asp_text(text)[0]


def script_spans(text: str) -> list[tuple[int, int]]:
    """The [start, end) character span of every #script block, judged outside strings and comments."""
    return _scan_asp_text(text)[1]


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

    A declared class covers both signs for round-trip and the name-collision
    check, but emits only "#show p/n." for the positive sign. If the block
    also derives classically negated atoms, declare -P as well so "#show
    -p/n." is emitted (P for positive, -P for negative).
    """

    def __init__(self, text: str, predicates: Sequence[PredicateClassType | NegatedSignature] = ()):
        if not isinstance(text, str):
            raise TypeError(f"RawASP text must be a string, got {type(text).__name__}")
        # A subclass converts to its natural plain str first: what the scan
        # below inspects is exactly what will render
        self.text = str(text)
        if directive := _find_unsupported_directive(self.text):
            if directive == "#external":
                raise ValueError(
                    "raw_asp() text contains #external, which pyclingo cannot honor: an "
                    "external atom's truth is set per solve through Control.assign_external, "
                    "which no pyclingo verb speaks — left unassigned the atom is false, and "
                    "every rule through it silently drops from the model. For a per-solve "
                    "switch, state the atom with choose(Choice(...)) and pin it with "
                    "assumptions= on solve()."
                )
            raise ValueError(
                f"raw_asp() text contains {directive}, which pyclingo cannot honor: the program "
                f"grounds a single 'base' part, so every statement rendered after a part "
                f"directive — including pyclingo-authored rules and #show lines — would land "
                f"in an unloaded part and silently vanish from the model. Inline the part's "
                f"statements directly (and for #include, paste the file's text)."
            )
        for entry in predicates:
            if isinstance(entry, Predicate):
                raise TypeError(
                    f"raw_asp() predicates declares CLASSES, got the atom {entry.render()} — "
                    f"pass the class {type(entry).__name__} (declaration covers every atom of "
                    f"the signature)"
                )
            if not isinstance(entry, NegatedSignature) and not (
                isinstance(entry, type) and issubclass(entry, Predicate)
            ):
                raise TypeError(
                    f"raw_asp() predicates entries must be Predicate classes (or -P for the "
                    f"negated sign), got {type(entry).__name__}"
                )
        self.predicates = tuple(predicates)

    def render(self) -> str:
        return self.text

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        # Raw text is invisible to the walkers, so predicates= declares its
        # atoms: P is the positive sign, -P (a NegatedSignature) the negative.
        # A raw block is always a top-level statement, so these are atoms.
        return {
            (entry.predicate, True, True) if isinstance(entry, NegatedSignature) else (entry, False, True)
            for entry in self.predicates
        }


class BlankLine(ProgramElement):
    """Represents a blank line in an ASP program for formatting."""

    locatable = False

    def render(self) -> str:
        return ""


def render_body_terms(terms: list[Term]) -> str:
    """
    Render a rule body's terms with the correct separators: a conditional
    literal's condition extends through commas, so the separator FOLLOWING
    one must be a semicolon — otherwise the next literal is absorbed into
    the condition. Shared by Rule and WeakConstraint.
    """
    parts = []
    for i, term in enumerate(terms):
        parts.append(term.render())
        if i < len(terms) - 1:
            parts.append("; " if isinstance(term, ConditionalLiteral) else ", ")
    return "".join(parts)


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
            result += render_body_terms(self.body)

        result += "."

        return result

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        if self.head is not None:
            constants.update(self.head.collect_defined_constants())

        for term in self.body:
            constants.update(term.collect_defined_constants())

        return constants

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        occurrences = (
            set() if self.head is None else set(self.head.collect_predicate_occurrences(as_argument=as_argument))
        )
        for term in self.body:
            occurrences.update(term.collect_predicate_occurrences(as_argument=as_argument))
        return occurrences
