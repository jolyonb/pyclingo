import math
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

import clingo

from pyclingo.choice import Choice
from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel
from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.conditioned_element import ConditionType
from pyclingo.core import Comparison, DefaultNegation, DefinedConstant, PredicateOccurrence, Term
from pyclingo.exceptions import GroundingError
from pyclingo.optimization import OptimizationTermType, OptStrategy, WeakConstraint
from pyclingo.predicate import NegatedSignature, Predicate
from pyclingo.program_elements import RawASP, RenderedLine, Rule, script_spans
from pyclingo.scoping import validate_rule
from pyclingo.segment import Segment, When
from pyclingo.solve_result import (
    OPTIMIZE,
    AtomCollection,
    BraveConsequences,
    CautiousConsequences,
    Consequences,
    CostedModel,
    OptimizeSteps,
    Optimum,
    RefinementMode,
    RefinementSteps,
    Search,
    SearchMode,
    SolveResult,
    convert_predicate_to_symbol,
)
from pyclingo.source_location import SourceLocation
from pyclingo.version import __version__


class _MinimizeLevelObserver(clingo.Observer):
    """
    Ground-program observer overriding ONLY minimize(): clingo registers a
    null callback for every method left on the base class, so grounding
    pays a Python call solely per ground optimization statement. The
    collected priorities are gringo's ground truth — exactly the levels
    clasp's cost tuple will have, empty tiers already dropped, raw text
    included. Note this captures all optimizations - minimize, maximize,
    and weak constraints - they all ground to minimize.
    """

    def __init__(self) -> None:
        self.priorities: set[int] = set()

    def minimize(self, priority: int, literals: Sequence[tuple[int, int]]) -> None:
        self.priorities.add(priority)


def _require_predicate_class(candidate: object, verb: str) -> None:
    """Visibility is per CLASS; failing here beats an AttributeError three stages later at render."""
    if isinstance(candidate, Predicate):
        if candidate.negated:
            # The class governs BOTH signs, so "pass the class" would
            # silently discard the sign this caller singled out
            raise TypeError(
                f"{verb}() takes a predicate class, got the negated atom {candidate.render()} — "
                f"pass the class {type(candidate).__name__} to govern both signs, or register a "
                f"show_when whose head is -{type(candidate).get_name()}(...) to govern the "
                f"negated sign alone"
            )
        raise TypeError(
            f"{verb}() takes a predicate class, got the atom {candidate.render()} — "
            f"pass the class {type(candidate).__name__} (visibility is per class, not per atom)"
        )
    if not (isinstance(candidate, type) and issubclass(candidate, Predicate)):
        raise TypeError(f"{verb}() takes a Predicate class, got {type(candidate).__name__}")


def _describe_class(pred: type[Predicate]) -> str:
    """The class name plus its definition site — colliding classes' names match by definition."""
    defined_at = pred._defined_at
    return f"{pred.__name__} defined at {defined_at.display()}" if defined_at is not None else pred.__name__


def _head_classes(head: Term) -> set[type[Predicate]]:
    """The classes a rule head derives: an atom's own, or a choice's element targets (conditions derive nothing)."""
    if isinstance(head, Predicate):
        return {type(head)}
    if isinstance(head, Choice):
        classes: set[type[Predicate]] = set()
        for element in head.elements:
            for target in element.targets:
                assert isinstance(target, Predicate)  # Choice.add admits nothing else
                classes.add(type(target))
        return classes
    # The remaining legal head is a Comparison, which acts as a requirement
    # on its body and derives no atoms
    return set()


def _validate_timeout(timeout: float) -> None:
    """The timeout checks, shared by _begin_solve and the sugar verbs (cheap checks before grounding is paid for)."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError(f"timeout is seconds (a number), got {type(timeout).__name__}")
    if timeout < 0 or not math.isfinite(timeout):
        # inf would pointlessly engage the async solver thread for a call
        # that means "no limit" — 0 already says that, without the thread
        raise ValueError(f"timeout must be non-negative and finite (0 means no limit), got {timeout}")


def _validate_max_iterations(max_iterations: int) -> None:
    """The max_iterations checks, shared by the eager folds and the sugar verbs."""
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
        raise TypeError(f"max_iterations is a count, got {type(max_iterations).__name__}")
    if max_iterations < 0:
        raise ValueError(f"max_iterations must be non-negative (0 means unbounded), got {max_iterations}")


def _annotate_lines(lines: list[RenderedLine]) -> list[RenderedLine]:
    """
    Append a "  % file:line" comment to each statement line, naming the
    user line that authored it. Appending (never inserting) keeps line
    numbering identical to the unannotated render, so the annotated text IS
    the reverse map: a raw-clingo error at line N is explained by the
    comment on line N. Every non-blank line of a multi-line statement gets
    its origin; formatting elements are never stamped so they stay bare,
    and so is any line a #script block touches — a note there would become
    part of the embedded script's source. Script extents come from the
    same character-level scan raw_asp validation uses, so blocks opening
    or closing mid-line are honored.
    """
    text = "\n".join(line.text for line in lines)
    spans = script_spans(text)
    starts: list[int] = []
    position = 0
    for line in lines:
        starts.append(position)
        position += len(line.text) + 1
    touched = {
        index
        for index, line in enumerate(lines)
        for span_start, span_end in spans
        if starts[index] < span_end and starts[index] + len(line.text) > span_start
    }
    annotated: list[RenderedLine] = []
    for index, line in enumerate(lines):
        line_text, element = line.text, line.element
        if element is not None and line_text != "" and index not in touched and element.source_location is not None:
            note = element.source_location.display()
            if element.closed_at is not None:
                note += f" (closed at {element.closed_at.display()})"
            line_text = f"{line_text}  % {note}"
        annotated.append(RenderedLine(line_text, element))
    return annotated


@dataclass(frozen=True)
class SignatureGrounding:
    """
    One row of a grounding profile: a signature's ground atom count and
    the statements that derive it. derived_at holds authoring locations,
    deduplicated in document order; None stands for a statement whose
    segment had source locations switched off, and an empty tuple means
    no pyclingo statement derives the signature (e.g. raw-text atoms
    declared only via show()).
    """

    name: str
    arity: int
    atom_count: int
    derived_at: tuple[SourceLocation | None, ...]


class ASPProgram:
    """
    Represents a complete ASP program.

    This class manages a collection of rules, comments, and other elements
    that make up an ASP program, and provides methods to build and render
    the program.
    """

    def __init__(
        self,
        header: str | None = None,
        default_segment: str = "Rules",
        allow_singletons: bool = False,
        source_locations: bool = True,
    ) -> None:
        """
        Initialize an empty ASP program.

        allow_singletons switches off the singleton-variable lint (a variable
        used exactly once is rejected as a likely typo). The lint is
        pyclingo-only — gringo is silent about singletons — so exploratory
        code may prefer it off; ANY remains the per-variable escape either
        way. Safety checks are not affected.

        source_locations stamps each statement with the user line that
        authored it, powering the dangling-when() report, render(annotate=
        True), and the "generated by file:line" note on grounding
        diagnostics. Capture costs a few microseconds per statement; switch
        it off when generating rules in bulk from code whose locations mean
        nothing. Like allow_singletons, the setting reaches segments this
        program creates; a Segment attached via add_segment keeps the
        setting it was constructed with. Freeze receipts on Choice and
        Aggregate (the mutation-after-capture error naming the capturing
        rule's line) are recorded regardless of this switch.
        """
        self._check_singletons = not allow_singletons
        self._source_locations = source_locations
        self._segments: dict[str, Segment] = {}
        self._defined_constants: dict[str, int | str | Predicate] = {}
        self._show_overrides: dict[type[Predicate], bool] = {}
        self._project_shown = False
        # Conditional shows are per SIGN: (class, negated) -> the directive's
        # conditional literal. Each sign's visibility resolves independently:
        # its conditional override, else the class's bool override/default.
        self._show_when_overrides: dict[tuple[type[Predicate], bool], ConditionalLiteral] = {}
        # The three assignable attributes go through their property setters,
        # so post-construction assignment gets the same validation
        self.header = header
        self.default_segment = default_segment

    def __setattr__(self, name: str, value: object) -> None:
        """
        Reject assignment to unknown public attributes: the assignable
        surface is exactly the settable properties, so a typo like
        program.project_show = True fails loudly instead of configuring
        nothing.
        """
        if not name.startswith("_"):
            attr = getattr(type(self), name, None)
            if not (isinstance(attr, property) and attr.fset is not None):
                assignable = ", ".join(
                    sorted(
                        {
                            key
                            for klass in type(self).__mro__
                            for key, member in vars(klass).items()
                            if isinstance(member, property) and member.fset is not None
                        }
                    )
                )
                raise AttributeError(
                    f"ASPProgram has no assignable attribute '{name}'; assignable attributes: "
                    f"{assignable}. (Underscored attributes are exempt — subclass state goes there.)"
                )
        super().__setattr__(name, value)

    @property
    def project_shown(self) -> bool:
        """
        When True, solution identity is the SHOWN atoms: models agreeing on
        every shown atom count as one (clingo's solve.project=show), so
        hidden helper predicates stop multiplying models. Assignable.
        """
        return self._project_shown

    @project_shown.setter
    def project_shown(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError(f"project_shown is a bool, got {type(value).__name__}")
        self._project_shown = value

    @property
    def header(self) -> str | None:
        """The one-line % comment at the top of the render; assignable."""
        return self._header

    @header.setter
    def header(self, value: str | None) -> None:
        if value is not None and not isinstance(value, str):
            raise TypeError(f"Program header must be a string, got {type(value).__name__}")
        # A subclass converts to its natural plain str first, so the check
        # below sees exactly the text that will render
        value = None if value is None else str(value)
        if value is not None and ("\n" in value or "\r" in value):
            raise ValueError("Program header must be a single line (it renders as one % comment)")
        if value is not None and "\x00" in value:
            raise ValueError(
                "Program header cannot contain NUL: clingo silently truncates the program at the first NUL byte"
            )
        self._header = value

    @property
    def default_segment(self) -> str:
        """The segment the program-level statement verbs write to; assignable (name rules apply on assignment)."""
        return self._default_segment_name

    @default_segment.setter
    def default_segment(self, name: str) -> None:
        self._default_segment_name = Segment.validate_name(name)

    def _default_segment(self) -> Segment:
        """The default segment, created on first use; every other segment needs add_segment."""
        key = self.default_segment
        if key not in self._segments:
            self._segments[key] = Segment(
                key,
                allow_singletons=not self._check_singletons,
                source_locations=self._source_locations,
            )
        return self._segments[key]

    def _existing_segment_key(self, segment: str) -> str:
        """The validated name of an existing segment; KeyError names the existing ones."""
        key = Segment.validate_name(segment)
        if key not in self._segments:
            existing = ", ".join(f"'{name}'" for name in self._segments) or "none"
            raise KeyError(f"Segment '{segment}' does not exist; existing segments: {existing}")
        return key

    def __getitem__(self, segment: str) -> Segment:
        """
        The named segment. Reading never creates: an unknown name raises
        KeyError naming the existing segments (add_segment is the one
        creation point; the default segment self-creates on first write).
        """
        return self._segments[self._existing_segment_key(segment)]

    def __setitem__(self, segment: str, value: Segment) -> None:
        """
        REPLACE an existing segment in place, rendering position
        preserved — the one thing add_segment cannot express. Assignment
        never creates (add_segment is the one creation point; a typo here
        must not silently append a segment at the end of the program), and
        the segment's own name must match the key: names are never rebound.
        """
        key = Segment.validate_name(segment)
        if not isinstance(value, Segment):
            raise TypeError(f"Expected a Segment, got {type(value).__name__}")
        if value.name != key:
            raise ValueError(
                f"Key '{key}' does not match the segment's name '{value.name}'; "
                f"names are never rebound — construct the Segment with the name you mean"
            )
        if key not in self._segments:
            existing = ", ".join(f"'{name}'" for name in self._segments) or "none"
            raise KeyError(
                f"Segment '{key}' does not exist, and assignment only replaces — "
                f"create segments with add_segment(). Existing segments: {existing}"
            )
        self._segments[key] = value

    def __contains__(self, segment: str) -> bool:
        """Whether a segment with this name exists (membership is by name, like a dict's)."""
        if isinstance(segment, Segment):
            raise TypeError(
                f"Membership is by name, like a dict's: use '{segment.name}' in program "
                f"(program['{segment.name}'] reads the attached object back for an identity check)"
            )
        if not isinstance(segment, str):
            raise TypeError(f"Segment membership is by name (a string), got {type(segment).__name__}")
        return str(segment) in self._segments

    def __iter__(self) -> Iterator[str]:
        """Iterate the segment names, in rendering order (dict convention: keys; .segments holds the objects)."""
        return iter(self._segments)

    def __len__(self) -> int:
        """The number of segments."""
        return len(self._segments)

    @property
    def segments(self) -> tuple[Segment, ...]:
        """The program's segments, in rendering order."""
        return tuple(self._segments.values())

    def add_segment(self, segment: str | Segment) -> Segment:
        """
        Add a segment, fixing its position in the rendered output, and
        return it: a string pre-declares an empty segment, a Segment
        object attaches it as-is (the program holds the object you gave
        it — appends through any handle are visible). Statements are then
        spoken on the returned handle, or on program["name"].

        Adding a name that already exists is an error, because its
        position is already set; assign with program["name"] = segment to
        replace one in place.
        """
        attached = (
            segment
            if isinstance(segment, Segment)
            else Segment(segment, allow_singletons=not self._check_singletons, source_locations=self._source_locations)
        )
        if attached.name in self._segments:
            given = segment if isinstance(segment, str) else segment.name
            raise ValueError(f"Segment '{given}' already exists")
        self._segments[attached.name] = attached
        return attached

    def __delitem__(self, segment: str) -> None:
        """
        Remove a segment and everything in it; KeyError (naming the
        existing segments) if absent. Existing groundings are unaffected.
        """
        del self._segments[self._existing_segment_key(segment)]

    def fact(self, *facts: Predicate) -> None:
        """Add unconditional statements to the default segment; see Segment.fact()."""
        self._default_segment().fact(*facts)

    def choose(self, choice: Choice) -> None:
        """Add a bare choice rule to the default segment; see Segment.choose()."""
        self._default_segment().choose(choice)

    def when(self, *conditions: Term) -> When:
        """Hold conditions for a closer, in the default segment; see Segment.when()."""
        return self._default_segment().when(*conditions)

    def forbid(self, *conditions: Term) -> None:
        """Forbid the combination, in the default segment; see Segment.forbid()."""
        self._default_segment().forbid(*conditions)

    def require(self, comparison: Comparison) -> None:
        """Require a comparison to hold, in the default segment; see Segment.require()."""
        self._default_segment().require(comparison)

    def minimize(
        self,
        weight: int | OptimizationTermType,
        *terms: OptimizationTermType,
        condition: ConditionType | list[ConditionType] | None = None,
        priority: int = 0,
    ) -> None:
        """Add a #minimize statement to the default segment; see Segment.minimize()."""
        self._default_segment().minimize(weight, *terms, condition=condition, priority=priority)

    def maximize(
        self,
        weight: int | OptimizationTermType,
        *terms: OptimizationTermType,
        condition: ConditionType | list[ConditionType] | None = None,
        priority: int = 0,
    ) -> None:
        """Add a #maximize statement to the default segment; see Segment.maximize()."""
        self._default_segment().maximize(weight, *terms, condition=condition, priority=priority)

    def penalize(
        self,
        *conditions: Term,
        weight: int | OptimizationTermType = 1,
        terms: Sequence[OptimizationTermType] | None = None,
        priority: int = 0,
    ) -> None:
        """Charge for each match of the conditions, in the default segment; see Segment.penalize()."""
        self._default_segment().penalize(*conditions, weight=weight, terms=terms, priority=priority)

    def raw_asp(self, text: str, predicates: Sequence[type[Predicate] | NegatedSignature] = ()) -> None:
        """Add verbatim ASP text to the default segment; see Segment.raw_asp()."""
        self._default_segment().raw_asp(text, predicates)

    def comment(self, text: str) -> None:
        """Add a comment to the default segment."""
        self._default_segment().comment(text)

    def blank_line(self) -> None:
        """Add a blank line to the default segment."""
        self._default_segment().blank_line()

    def section(self, title: str) -> None:
        """Add a blank line and title comment to the default segment."""
        self._default_segment().section(title)

    def define_constant(self, name: str, value: int | str | Predicate) -> DefinedConstant:
        """
        Define a #const constant, rendered as "#const name = value.".

        A str value is a STRING: it renders quoted, and a quoted string is a
        different value from a bare symbol ("n" never equals n). To define a
        symbolic constant, pass a grounded atom — define_constant("dir", N())
        with N = Predicate.define("n", []) renders "#const dir = n.".

        Raises:
            ValueError: If the name is invalid or already defined.
        """
        if not isinstance(name, str):
            raise TypeError(f"Constant name must be a string, got {type(name).__name__}")
        name = str(name)  # a subclass's natural plain form: the checks below see what renders
        if isinstance(value, int) and not isinstance(value, bool) and not -(2**31) <= value < 2**31:
            raise ValueError(
                f"Constant value {value} is outside clingo's integer range "
                f"[-2147483648, 2147483647]; clingo would silently wrap it"
            )
        constant = DefinedConstant(name)  # the one home for constant-name rules
        if name in self._defined_constants:
            raise ValueError(f"Defined constant '{name}' is already registered")

        if isinstance(value, bool) or not isinstance(value, (int, str, Predicate)):
            # bool subclasses int, and a boolean is never a valid ASP term
            raise TypeError(
                f"Constant value must be an integer, a string, or a grounded predicate "
                f"atom (a bare atom names clingo's symbolic constant), got {type(value).__name__}"
            )
        if isinstance(value, Predicate):
            if not value.is_grounded:
                variables = ", ".join(sorted(value.collect_variables()))
                raise ValueError(
                    f"A #const value must be a ground term, but {value.render()} contains variable(s) {variables}"
                )
            if referenced := value.collect_defined_constants():
                raise ValueError(
                    f"A #const value cannot reference other defined constants "
                    f"({', '.join(sorted(referenced))} in {value.render()}): register the "
                    f"plain value directly"
                )
        else:
            # A subclass converts to its natural plain form first, so the check
            # below sees exactly the value that will render
            value = int(value) if isinstance(value, int) else str(value)
            if isinstance(value, str) and any(c in value for c in ('"', "\\", "\n", "\r", "\x00")):
                raise ValueError(
                    f"Constant string value cannot contain quotes, backslashes, newlines, or NUL: {value!r}"
                )

        self._defined_constants[name] = value

        return constant

    @property
    def defined_constants(self) -> dict[str, int | str | Predicate]:
        """The #const definitions registered so far, name to value (a copy — register through define_constant())."""
        return dict(self._defined_constants)

    def show(self, predicate: type[Predicate]) -> None:
        """
        Show this predicate in output, overriding its default visibility.

        Showing a predicate the program never derives is an error at render
        when it is provably absent; if the atoms come from a raw_asp() block,
        the check cannot see them, and an absent signature instead fails at
        solve with gringo's "no atoms over signature" info.
        """
        _require_predicate_class(predicate, "show")
        self._show_overrides[predicate] = True

    def hide(self, predicate: type[Predicate]) -> None:
        """
        Hide this predicate from output, overriding its default visibility.

        Hiding a class that only ever appears nested inside other atoms is
        vacuous: argument-position data cannot be hidden, and no error is
        raised (hide states an intent; show() of an underived class errors
        because it states an expectation).

        Hidden atoms are absent from every result — never touching them is
        what keeps model reads fast at scale — and asking a result for a
        hidden class raises with the remedy rather than returning [].
        """
        _require_predicate_class(predicate, "hide")
        self._show_overrides[predicate] = False

    def show_when(self, condition: ConditionalLiteral) -> None:
        """
        Show a predicate only where the condition holds. The shown predicate
        is the conditional literal's head, e.g.

            show_when(ConditionalLiteral(p(C), [p(C), ~outside(C)]))

        renders as "#show p(C) : p(C), not outside(C)."

        The directive covers the head's SIGN only: a positive head governs
        positive atoms, a classically negated head (-p(...)) governs the
        negated atoms, and the two may be registered independently — the
        other sign falls back to the class's show()/hide()/default. For
        its own sign a conditional outranks show()/hide() regardless of
        call order (resolution is by kind, not time). A sign takes ONE
        conditional: registering a second for the same (class, sign)
        raises, and there is no way to unregister one.
        """
        if not isinstance(condition, ConditionalLiteral):
            raise TypeError(f"show_when condition must be a ConditionalLiteral, got {type(condition).__name__}")
        head = condition.head
        if not isinstance(head, Predicate):
            raise ValueError(
                f"show_when needs a conditional literal whose head is a predicate atom "
                f"(the thing to show), got {type(head).__name__}"
            )
        key = (type(head), head.negated)
        if key in self._show_when_overrides:
            sign = "-" if head.negated else ""
            raise ValueError(
                f"show_when is already registered for {sign}{type(head).get_name()}/{type(head).get_arity()} "
                f"(#show {self._show_when_overrides[key].render()}.); a sign takes one conditional "
                f"directive — combine the conditions into a single show_when"
            )
        # A show directive is a capture too: freeze so later mutation of a
        # shared builder cannot silently rewrite it, and validate its variables
        # (a #show directive has no rule body, so everything must be bound
        # inside the conditional literal itself)
        validate_rule(None, [condition], f"#show {condition.render()}.", check_singletons=self._check_singletons)
        condition.freeze()
        self._show_when_overrides[key] = condition

    def _has_raw_asp(self) -> bool:
        """Whether any segment contains a RawASP block (raw text is invisible to the tree walkers)."""
        return any(isinstance(element, RawASP) for segment in self._segments.values() for element in segment)

    def _validate_shown_predicates(self, segment_occurrences: set[PredicateOccurrence], has_raw: bool) -> None:
        """
        Raise for show()/show_when() of atoms nothing derives — but only when
        the program has no raw_asp blocks: raw text is invisible to the
        walkers, so with raw blocks present an uncollected predicate may
        still be derived (that is what raw_asp's predicates= is for).
        """
        if has_raw:
            return
        # Derivation evidence comes from the program's own rules: a show_when
        # condition's atoms must not vouch for themselves
        atom_occurrences = {(cls, negated) for cls, negated, is_atom in segment_occurrences if is_atom}
        atom_classes = {cls for cls, _negated in atom_occurrences}
        for pred, visibility in self._show_overrides.items():
            if visibility is True and pred not in atom_classes:
                raise ValueError(
                    f"show({pred.__name__}) was called, but no {pred.get_name()}/{pred.get_arity()} "
                    f"atoms occur anywhere in the program — nothing derives it. (If it were "
                    f"emitted, gringo would reject the dangling #show directive.)"
                )
        for pred, negated in self._show_when_overrides:
            if (pred, negated) not in atom_occurrences:
                sign = "-" if negated else ""
                raise ValueError(
                    f"show_when was registered for {sign}{pred.get_name()}/{pred.get_arity()}, "
                    f"but no such atoms occur anywhere in the program — nothing derives them."
                )

    def _validate_names(self, all_classes: set[type[Predicate]]) -> None:
        """
        Raise on naming collisions that would corrupt solving:

        - two distinct predicate classes sharing (name, arity): solutions could not
          be reconstructed unambiguously
        - a nullary predicate sharing its name with a #const: gringo substitutes
          the constant only in TERM positions, so the atom stays a distinct,
          silently unrelated symbol
        """
        by_signature: dict[tuple[str, int], type[Predicate]] = {}
        for pred in all_classes:
            key = (pred.get_name(), pred.get_arity())
            if pred.get_arity() == 0 and key[0] in self._defined_constants:
                raise ValueError(
                    f"'{key[0]}' is both a #const and a nullary predicate: gringo would "
                    f"silently substitute the constant's value into every occurrence of "
                    f"the atom. Rename one of them."
                )
            other = by_signature.get(key)
            if other is not None and other is not pred:
                raise ValueError(
                    f"Predicate name collision: '{key[0]}/{key[1]}' is produced by two distinct "
                    f"classes ({_describe_class(other)} and {_describe_class(pred)}); solutions "
                    f"cannot be reconstructed unambiguously. Give one a namespace in Predicate.define()."
                )
            by_signature[key] = pred

    def render(self, annotate: bool = False) -> str:
        """
        Render the complete ASP program, in order:

        1. Header comments
        2. #const definitions (every registered constant — raw_asp text may use them, so none are filtered)
        3. Program segments (rules, comments, section headers)
        4. #show directives (one deduplicated block, sorted)

        annotate=True appends a "  % file:line" comment to each statement
        line, naming the user line that authored it; statements with no
        recorded location (capture off in their segment) stay bare. Line
        numbering is unchanged from the plain render, so the annotated text
        doubles as the reverse map: a raw-clingo error at line N is
        explained by the comment on line N. Off by default: annotated
        output churns on unrelated edits, so keep checked-in or
        golden-compared renders unannotated.
        """
        lines, _all_classes, _has_raw = self._render_lines(annotate=annotate)
        return "\n".join(line.text for line in lines) + "\n"

    def _render_with_origins(self) -> tuple[str, dict[int, SourceLocation], set[type[Predicate]], bool]:
        """
        The rendered program, a 1-based line -> authoring-location map for
        grounding diagnostics, and the walk products ground() reuses: the
        program's full class universe and whether raw blocks exist.
        """
        lines, all_classes, has_raw = self._render_lines(annotate=False)
        origins = {
            line_number: line.element.source_location
            for line_number, line in enumerate(lines, start=1)
            if line.element is not None and line.element.source_location is not None
        }
        return "\n".join(line.text for line in lines) + "\n", origins, all_classes, has_raw

    def _render_lines(self, annotate: bool) -> tuple[list[RenderedLine], set[type[Predicate]], bool]:
        """
        Every rendered line carrying the element that produced it
        (program-level lines carry None) — plus the class universe and the
        raw-block flag, computed by the render's one occurrence walk so
        ground() never re-walks the tree. The universe covers every door
        (segment elements, show_when conditions, show()/hide() overrides):
        it is the reconstruction registry and the raw_asp declaration
        contract's world — naming a class to show() declares it as fully
        as predicates= does.
        """
        for segment in self._segments.values():
            segment.check_pending()
        self._validate_constants()
        # The predicate-occurrence walk is the render's hot spot: computed
        # once here, shared by both validators and the show block below
        segment_occurrences = {
            occ for segment in self._segments.values() for occ in segment.collect_predicate_occurrences()
        }
        show_when_occurrences = {
            occ
            for condition in self._show_when_overrides.values()
            for occ in condition.collect_predicate_occurrences(as_argument=False)
        }
        all_classes = (
            {cls for cls, _negated, _is_atom in segment_occurrences | show_when_occurrences}
            | set(self._show_overrides)
            # Atom-valued #const definitions: their classes join the walk so
            # solution atoms carrying the symbol reconstruct typed, and the
            # name-collision walls see them
            | {
                cls
                for value in self._defined_constants.values()
                if isinstance(value, Predicate)
                for cls in value.collect_predicates()
            }
        )
        has_raw = self._has_raw_asp()
        self._validate_names(all_classes)
        self._validate_shown_predicates(segment_occurrences, has_raw)

        # Discriminate auto-tupled weak constraints program-wide, in document
        # order: two statements' coinciding ground tuples must not merge
        # charges in the shared tuple set. A program-level concern like the
        # #show block, computed fresh into a render-local map each render —
        # rendering never mutates elements, so programs sharing a segment
        # cannot interfere, however they are threaded. Uniqueness within one
        # render is the guarantee; ordinals stay stable across renders while
        # the program only appends (deleting or replacing a segment shifts
        # later ordinals).
        weak_discriminators: dict[int, int] = {}
        for segment in self._segments.values():
            for element in segment:
                if isinstance(element, WeakConstraint) and element.auto_tuple:
                    weak_discriminators[id(element)] = len(weak_discriminators)

        # 1. Header comments
        lines: list[str] = []
        if self.header:
            lines.append(f"% {self.header}")
        lines.append(f"% Generated by pyclingo {__version__}")
        if self.project_shown:
            # The projection lives in solver config, not program text: anyone
            # running this file with raw clingo needs --project=show
            lines.append("% Solution identity: projected onto shown atoms (run raw clingo with --project=show)")

        # 2. #const definitions. Every registered constant is emitted: the tree
        # walkers cannot see into raw_asp text, so filtering to "used" constants
        # silently dropped declarations that raw blocks relied on
        for name, value in self._defined_constants.items():
            if isinstance(value, str):
                lines.append(f'#const {name} = "{value}".')  # String values are quoted
            elif isinstance(value, Predicate):
                lines.append(f"#const {name} = {value.render()}.")  # a bare atom: a symbolic constant
            else:
                lines.append(f"#const {name} = {value}.")  # Integer values are not

        rendered: list[RenderedLine] = [RenderedLine(line, None) for line in lines]

        # 3. Program segments: headers only when more than one segment actually
        # renders (empty segments don't count), with a blank line between
        # rendered segments (none before the first)
        with_headers = sum(1 for segment in self._segments.values() if len(segment) > 0) > 1
        first_segment = True
        for segment in self._segments.values():
            if len(segment) == 0:
                continue
            if with_headers and not first_segment:
                rendered.append(RenderedLine("", None))
            first_segment = False
            segment_lines = segment.render_lines(with_header=with_headers, weak_discriminators=weak_discriminators)
            rendered.extend(_annotate_lines(segment_lines) if annotate else segment_lines)

        # 4. #show directives: one deduplicated block, emitted sorted.
        # The bare "#show." must be emitted whenever ANY predicate is hidden, even if
        # nothing is shown — without it, clingo defaults to showing every atom.
        show_statements: set[str] = set()
        any_hidden = False
        # Visibility resolves PER SIGN: a sign's conditional override wins,
        # else the class's bool override/default. Signature directives are
        # emitted only for present signs (a directive for an absent signature
        # draws a gringo info); an explicit show() counts as positive
        # presence only where a positive atom could exist — walked, or
        # possibly hiding in raw text.
        # Presence comes from the program's own segments (raw declarations
        # included) — the same evidence validation used above, so a show_when
        # condition can never vouch a dangling directive past the check
        walked_positive = {cls for cls, negated, is_atom in segment_occurrences if is_atom and not negated}
        override_positive = {
            cls
            for cls, visibility in self._show_overrides.items()
            if visibility is True and (cls in walked_positive or has_raw)
        }
        positive_classes = walked_positive | override_positive
        negated_classes = {cls for cls, negated, is_atom in segment_occurrences if is_atom and negated}
        for pred in all_classes:
            bool_visibility = self._show_overrides.get(pred, pred.shown_by_default())
            for negated, present_set in ((False, positive_classes), (True, negated_classes)):
                conditional = self._show_when_overrides.get((pred, negated))
                if conditional is not None:
                    show_statements.add(f"#show {conditional.render()}.")
                elif bool_visibility:
                    if pred in present_set:
                        sign = "-" if negated else ""
                        show_statements.add(f"#show {sign}{pred.get_name()}/{pred.get_arity()}.")
                else:
                    any_hidden = True
        if show_statements or any_hidden:
            rendered.extend(RenderedLine(line, None) for line in ("", "#show.", *sorted(show_statements)))

        return rendered, all_classes, has_raw

    def _collect_used_defined_constants(self) -> set[str]:
        """Collect all defined constant names used anywhere in the program."""
        constants = set()

        for segment in self._segments.values():
            constants.update(segment.collect_defined_constants())

        for condition in self._show_when_overrides.values():
            constants.update(condition.collect_defined_constants())

        return constants

    def _validate_constants(self) -> None:
        """Raise if any constant used in the program was never declared via define_constant()."""
        used_constants = self._collect_used_defined_constants()

        if unregistered := used_constants - set(self._defined_constants.keys()):
            raise ValueError(f"Undefined constants used in program: {', '.join(sorted(unregistered))}")

    def ground(self, stop_on_log_level: LogLevel = LogLevel.INFO, context: object = None) -> GroundedProgram:
        """
        Render and ground the program once, returning a handle that can be
        solved repeatedly — the re.compile() of this API. solve() is sugar
        for ground().solve(); use ground() directly when the same program
        will be solved many times (grounding is the expensive step).

        context is clingo's grounding context, passed through verbatim: an
        object whose methods back @-function calls in raw_asp() text
        (@stone(...) calls context.stone(...)). Raw-clingo territory —
        pyclingo does not model @-terms, so the text and the context must
        agree on their own.

        The handle is an independent snapshot — it holds the rendered text
        and solves exactly that program forever, like a compiled regex holds
        its pattern. Mutating this ASPProgram afterwards does not affect
        existing handles; ground() again for the updated program (keeping
        both handles is fine, e.g. to compare a program with and without a
        rule).

        Raises:
            ValueError: For render-time validation failures (undeclared
                constants, name collisions, shows of underived predicates)
            GroundingError: If an error occurs during parsing or grounding,
                or the log level threshold is exceeded
        """
        asp_source, line_origins, all_classes, has_raw = self._render_with_origins()

        message_handler = ClingoMessageHandler(asp_source, stop_on_level=stop_on_log_level, line_origins=line_origins)
        control = clingo.Control(logger=message_handler.on_message, arguments=["--stats"])
        # Ground truth for optimization: the observer receives gringo's own
        # minimize statements as they ground, so the surviving priority
        # levels are known exactly — raw text included, empty tiers dropped
        observer = _MinimizeLevelObserver()
        control.register_observer(observer)

        try:
            control.add("base", [], asp_source)
        except RuntimeError as e:
            error_msg = str(e)
            if formatted_messages := message_handler.format_all_messages(verb="parsing"):
                error_msg += "\n\n" + formatted_messages
            raise GroundingError(error_msg, messages=message_handler.messages) from e

        try:
            control.ground([("base", [])], context=context)
        except RuntimeError as e:
            error_msg = f"Grounding failed: {e}\n\n"
            if formatted_messages := message_handler.format_all_messages(verb="grounding"):
                error_msg += formatted_messages
            raise GroundingError(error_msg, messages=message_handler.messages) from e

        # Messages below the stop threshold are tolerated silently; at or above
        # it, the full formatted diagnostics ride along in the raised error
        if message_handler.should_halt:
            assert message_handler.highest_level is not None
            raise GroundingError(
                f"Grounding produced {message_handler.highest_level.name} level messages "
                f"(stop threshold: {stop_on_log_level.name}).\n\n"
                f"{message_handler.format_all_messages(verb='grounding')}",
                messages=message_handler.messages,
            )

        # Cost-tuple and bound positions follow these levels, highest first
        ground_levels = tuple(sorted(observer.priorities, reverse=True))
        if self.project_shown and ground_levels:
            raise ValueError(
                "project_shown cannot be combined with optimization: clasp warns that "
                "optimization may depend on enumeration order under projection, so the "
                "reported optimum may not be the true one. Disable projection for "
                "optimizing programs."
            )
        if self.project_shown:
            assert isinstance(control.configuration.solve, clingo.Configuration)
            control.configuration.solve.project = "show"

        predicate_types = {(pred.get_name(), pred.get_arity()): pred for pred in all_classes}

        # The FULLY hidden classes: no bool visibility and no conditional
        # show on either sign. Their atoms are never read back into models
        # (the shown set is what keeps model reads fast at scale), so the
        # read surfaces raise a teaching error instead of a silent [].
        hidden_classes = frozenset(
            pred
            for pred in predicate_types.values()
            if not self._show_overrides.get(pred, pred.shown_by_default())
            and not any((pred, negated) in self._show_when_overrides for negated in (False, True))
        )

        # Deriving statements by signature, for analyze_grounding(): each
        # rule head's classes and each raw block's declared classes, joined
        # to the source lines that authored them
        derivation_sites: dict[tuple[str, int], list[SourceLocation | None]] = {}
        for segment in self._segments.values():
            for element in segment:
                classes: set[type[Predicate]] = set()
                if isinstance(element, Rule) and element.head is not None:
                    classes = _head_classes(element.head)
                elif isinstance(element, RawASP):
                    classes = {
                        entry.predicate if isinstance(entry, NegatedSignature) else entry
                        for entry in element.predicates
                    }
                for cls in classes:
                    derivation_sites.setdefault((cls.get_name(), cls.get_arity()), []).append(element.source_location)

        # Raw text is invisible to the walkers, so with raw blocks present
        # the raw_asp contract (exhaustive declaration) is enforced here,
        # against gringo's own signature table: every ground signature must
        # be a declared class.
        if has_raw:
            undeclared = sorted(
                {(name, arity) for name, arity, _positive in control.symbolic_atoms.signatures} - set(predicate_types)
            )
            if undeclared:
                for name, arity in undeclared:
                    if arity == 0 and name in self._defined_constants:
                        raise ValueError(
                            f"'{name}' is both a #const and an atom in the grounding: gringo "
                            f"substitutes the constant only in TERM positions, so the atom "
                            f"stays a distinct, silently unrelated symbol. Rename one of them."
                        )
                listing = ", ".join(f"{name}/{arity}" for name, arity in undeclared)
                raise ValueError(
                    f"The grounded program contains predicates never declared to pyclingo: "
                    f"{listing}. raw_asp blocks must declare every predicate occurring in "
                    f"their text via predicates=[...]; control visibility with show= on "
                    f"the class, not by omitting it."
                )

        return GroundedProgram(
            asp_source,
            control,
            predicate_types,
            message_handler,
            defined_constants=dict(self._defined_constants),
            ground_levels=ground_levels,
            derivation_sites={signature: tuple(sites) for signature, sites in derivation_sites.items()},
            hidden_classes=hidden_classes,
        )

    def solve(
        self,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        stop_on_log_level: LogLevel = LogLevel.INFO,
        ignore_optimization: bool = False,
    ) -> SolveResult:
        """
        Solve the ASP program, returning a SolveResult that yields Models lazily.

        Sugar for ground().solve(): renders and grounds a fresh Control every
        call. For solving one program many times, call ground() once and
        solve the returned handle repeatedly.

        The stream is unbounded: take what you need (next(iter(result)) for
        one model, itertools.islice for N, a for-loop with break for a
        condition) — clasp computes the next model only when you resume, so
        nothing runs ahead of your consumption. Whole-stream reads
        (list(result), a bare for-loop) enumerate EVERY model, which an
        underconstrained program can make effectively endless.

        Args:
            timeout: Wall-clock limit in seconds (0 for no limit), counted from the
                     start of iteration. On timeout, models found so far will have
                     been yielded and 'exhausted' remains False; a timeout before
                     ANY model raises TimeoutError.
            assumptions: Atoms fixed for this solve only (a grounded Predicate
                assumes it true, ~Predicate false); see GroundedProgram.solve().
            stop_on_log_level: Log level at which to abort — applies to parsing
                and grounding. Solve-phase messages never halt; they are
                captured on each Model (.messages) and the SolveResult
            ignore_optimization: Enumerate answer sets as if the program had
                no #minimize/#maximize (clasp's opt_mode=ignore); see
                GroundedProgram.solve(). Requires an objective to ignore.

        Returns:
            A SolveResult: iterate it for Models (each with typed atoms() access);
            its satisfiable/exhausted/models_yielded/statistics finalize when
            iteration ends on any path (exhaustion, close(), or a with-block).

        Raises:
            ValueError: For render-time validation failures (undeclared
                constants, name collisions, shows of underived predicates)
            GroundingError: If an error occurs during parsing or grounding, or
                the log level threshold is exceeded

        Notes:
            Rendering, grounding, and their error checks run eagerly at this call; only
            model enumeration is lazy. Every call returns an independent SolveResult,
            so repeated solves on one program never interfere.
        """
        _validate_timeout(timeout)  # before grounding is paid for
        return self.ground(stop_on_log_level=stop_on_log_level).solve(
            timeout=timeout, assumptions=assumptions, ignore_optimization=ignore_optimization
        )

    def cautious(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        stop_on_log_level: LogLevel = LogLevel.INFO,
        ignore_optimization: bool = False,
    ) -> CautiousConsequences | None:
        """
        The atoms true in every answer set; sugar for ground().cautious().
        See GroundedProgram.cautious(). For the stepwise cautious_iter()
        form, call ground() and use the handle — stepwise control belongs
        with a grounding you keep.
        """
        _validate_timeout(timeout)  # before grounding is paid for
        _validate_max_iterations(max_iterations)
        return self.ground(stop_on_log_level=stop_on_log_level).cautious(
            timeout=timeout,
            max_iterations=max_iterations,
            assumptions=assumptions,
            ignore_optimization=ignore_optimization,
        )

    def brave(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        stop_on_log_level: LogLevel = LogLevel.INFO,
        ignore_optimization: bool = False,
    ) -> BraveConsequences | None:
        """
        The atoms true in at least one answer set; sugar for
        ground().brave(). See GroundedProgram.brave(). For the stepwise
        brave_iter() form, call ground() and use the handle — stepwise
        control belongs with a grounding you keep.
        """
        _validate_timeout(timeout)  # before grounding is paid for
        _validate_max_iterations(max_iterations)
        return self.ground(stop_on_log_level=stop_on_log_level).brave(
            timeout=timeout,
            max_iterations=max_iterations,
            assumptions=assumptions,
            ignore_optimization=ignore_optimization,
        )

    def optimize(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        strategy: OptStrategy = OptStrategy.BB,
        all_optima: bool = False,
        bound: int | Mapping[int, int] | None = None,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        stop_on_log_level: LogLevel = LogLevel.INFO,
    ) -> Optimum | None:
        """
        The best answer set by the objectives; sugar for
        ground().optimize(). See GroundedProgram.optimize(). For the
        stepwise optimize_iter() form, call ground() and use the handle —
        stepwise control belongs with a grounding you keep.
        """
        _validate_timeout(timeout)  # before grounding is paid for
        _validate_max_iterations(max_iterations)
        return self.ground(stop_on_log_level=stop_on_log_level).optimize(
            timeout=timeout,
            max_iterations=max_iterations,
            strategy=strategy,
            all_optima=all_optima,
            bound=bound,
            assumptions=assumptions,
        )


class GroundedProgram:
    """
    A program rendered and grounded once, solvable many times.

    Obtained from ASPProgram.ground(). The handle is an independent
    snapshot: it holds the rendered text (the .text property) and solves
    exactly that program, unaffected by later mutation of the ASPProgram it
    came from — like a compiled regex and its pattern. Each solve() returns
    an independent SolveResult sharing this handle's single grounding, so
    the grounding step is paid once. One grounding answers many kinds of
    question: solve() enumerates answer sets, cautious()/brave() compute
    the atoms true in every/some answer set, optimize() finds the best
    answer set by the program's objectives, and every eager verb has a
    lazy twin (cautious_iter, brave_iter, optimize_iter — the
    findall/finditer pairing) for stepwise control. Assumptions
    parameterize any of them per call.

    One contract, enforced loudly: solves are sequential. A Control cannot
    run overlapping searches, so solve() raises while a previous result is
    unconsumed (consume it, close() it, or leave its with-block first).

    clingo's statistics reflect the most recent search on the shared
    Control; every handle (SolveResult and RefinementSteps alike) snapshots
    them, plus its own wall_time, as it finishes.
    """

    def __init__(
        self,
        text: str,
        control: clingo.Control,
        predicate_types: dict[tuple[str, int], type[Predicate]],
        message_handler: ClingoMessageHandler,
        defined_constants: dict[str, int | str | Predicate],
        ground_levels: tuple[int, ...],
        derivation_sites: dict[tuple[str, int], tuple[SourceLocation | None, ...]],
        hidden_classes: frozenset[type[Predicate]],
    ) -> None:
        self._text = text
        self._control = control
        self._predicate_types = predicate_types
        self._message_handler = message_handler
        self._defined_constants = defined_constants
        # Signature -> the authoring lines of its deriving statements, for
        # analyze_grounding()
        self._derivation_sites = derivation_sites
        # Classes whose atoms are never shown: read surfaces teach instead
        # of returning a silent empty
        self._hidden_classes = hidden_classes
        # Ground truth from the minimize observer: the surviving priority
        # levels, highest first — bool(levels) IS "does this program optimize?"
        self._ground_levels = ground_levels
        self._active: Search | None = None
        # Guards the guard: the sequential-solve check is check-then-set, so
        # two racing threads could both pass it and share one Control's
        # search state silently — the exact quiet overlap the check exists
        # to make loud. Held across check, configure, and _active assignment.
        self._solve_lock = threading.Lock()

    @property
    def text(self) -> str:
        """The rendered ASP program this grounding solves."""
        return self._text

    @property
    def control(self) -> clingo.Control:
        """
        The underlying clingo Control: the escape hatch to clingo internals
        (configuration, externals, theory atoms, observers) — at your own
        risk. pyclingo's guarantees stop here: direct mutations bypass the
        sequential-solve guard, the per-solve configuration the verbs
        restate on every entry, and the message bookkeeping. Reconfigure
        between solves, never during one, and prefer the pyclingo verbs
        where they exist.
        """
        return self._control

    @property
    def optimization_levels(self) -> tuple[int, ...]:
        """
        The SURVIVING optimization priority levels, highest first — ground
        truth from gringo (a declared tier whose elements ground empty is
        absent). Empty means the program does not optimize. Cost tuples
        and bounds follow these levels.
        """
        return self._ground_levels

    def grounding_profile(self) -> tuple[SignatureGrounding, ...]:
        """
        Where the grounding's size comes from, as data: one
        SignatureGrounding per signature, largest atom count first, each
        joined to the statements that derive it. Counts are gringo's
        ground truth (atoms simplified away at grounding are already
        gone; both signs of a signature count together).
        analyze_grounding() renders exactly this as prose.
        """
        counts: dict[tuple[str, int], int] = {}
        for name, arity, positive in self._control.symbolic_atoms.signatures:
            tally = sum(1 for _ in self._control.symbolic_atoms.by_signature(name, arity, positive=positive))
            counts[(name, arity)] = counts.get((name, arity), 0) + tally
        profile: list[SignatureGrounding] = []
        for (name, arity), count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            deduped: list[SourceLocation | None] = []
            for site in self._derivation_sites.get((name, arity), ()):
                if site not in deduped:
                    deduped.append(site)
            profile.append(SignatureGrounding(name, arity, count, tuple(deduped)))
        return tuple(profile)

    def analyze_grounding(self) -> str:
        """
        The grounding profile as prose: ground atom counts per signature,
        largest first, each joined to the authoring lines that derive it.
        The first stop when grounding is slow or huge — the top rows name
        the lines to rethink. grounding_profile() is the same data,
        structured.

        One blind spot, stated plainly: the report joins on HEADS, so a
        statement whose body grounds large without deriving new atoms
        (a wide joint feeding a small head) shows up under its head's
        count, not as its own row.
        """
        profile = self.grounding_profile()
        total = sum(entry.atom_count for entry in profile)
        lines = [f"Grounding profile: {total} ground atoms across {len(profile)} signatures"]
        for entry in profile:
            described = [
                site.display() if site is not None else "unknown (source locations off)" for site in entry.derived_at
            ]
            origin = ", ".join(described) if described else "no pyclingo statement (declared but underived?)"
            lines.append(f"  {entry.name}/{entry.arity}: {entry.atom_count} atoms — derived at {origin}")
        return "\n".join(lines)

    def _convert_assumptions(
        self, assumptions: Sequence[Predicate | DefaultNegation]
    ) -> list[tuple[clingo.Symbol, bool]]:
        """Convert assumption literals to (symbol, truth) pairs, existence-checked."""
        converted: list[tuple[clingo.Symbol, bool]] = []
        for literal in assumptions:
            if isinstance(literal, DefaultNegation):
                inner = literal.term
                truth = False
            else:
                inner = literal
                truth = True
            if not isinstance(inner, Predicate):
                if isinstance(inner, type) and issubclass(inner, Predicate):
                    raise TypeError(
                        f"Assumptions are atoms, got the predicate class {inner.__name__} — "
                        f"pass a grounded instance: {inner.__name__}(...)"
                    )
                described = (
                    f"~{type(inner).__name__}" if isinstance(literal, DefaultNegation) else type(literal).__name__
                )
                raise TypeError(f"Assumptions must be grounded predicate atoms or their ~negations, got {described}")
            if not inner.is_grounded:
                raise ValueError(f"Assumptions must be grounded: {inner.render()} contains variables")
            symbol = convert_predicate_to_symbol(inner, self._defined_constants)
            if symbol not in self._control.symbolic_atoms:
                raise ValueError(
                    f"Assumption {inner.render()} does not occur in this grounding — assuming "
                    f"an absent atom silently empties (or is vacuous over) the model set. "
                    f"Check the atom's spelling and arguments."
                )
            converted.append((symbol, truth))
        return converted

    def _begin_solve(
        self,
        mode: SearchMode,
        timeout: float,
        assumptions: Sequence[Predicate | DefaultNegation] | None,
        ignore_optimization: bool = False,
    ) -> list[tuple[clingo.Symbol, bool]] | None:
        """
        The whole pre-solve sequence, shared by every solve-flavored call:
        validate the timeout, convert assumptions, enforce the sequential
        guard, clear the message list (the guard proves no generator is
        mid-flight holding a window index, so clearing is safe), and
        configure the Control. enum_mode is stated explicitly on every
        entry, and models is always 0: streams are unbounded by design —
        the consumer's consumption is the limit (clasp computes the next
        model only when resumed, so nothing runs ahead of demand), and a
        cap would silently truncate refinements. Returns the converted
        assumptions.
        """
        _validate_timeout(timeout)
        if ignore_optimization and not self._ground_levels:
            raise ValueError("Nothing to ignore: this program has no #minimize/#maximize. Call the function plainly.")
        if self._ground_levels and mode is None and not ignore_optimization:
            raise ValueError(
                "This program optimizes (#minimize/#maximize present). Solve it "
                "with optimize(), or pass ignore_optimization=True to enumerate "
                "answer sets as if there were no objective."
            )
        if self._ground_levels and isinstance(mode, RefinementMode) and not ignore_optimization:
            raise ValueError(
                f"{mode.value} consequences over an optimizing program are computed "
                f"against the solver's cost-descent path, not the set of answer "
                f"sets. Pass ignore_optimization=True to refine over ALL answer "
                f"sets as if there were no objective, or remove the optimization "
                f"directive."
            )
        if mode == OPTIMIZE and not self._ground_levels:
            raise ValueError(
                "Nothing to optimize: this program has no #minimize/#maximize. "
                "Add minimize()/maximize() to state an objective, or enumerate "
                "with solve()."
            )
        converted = self._convert_assumptions(assumptions) if assumptions else None
        if self._active is not None and not self._active.finished:
            raise RuntimeError(
                "The previous solve on this grounding is still open; a Control cannot run "
                "overlapping searches. Consume the previous result, close() it, leave "
                "its with-block, or call abandon() on this grounding."
            )
        self._message_handler.messages.clear()
        solve_config = self._control.configuration.solve
        assert isinstance(solve_config, clingo.Configuration)
        solve_config.models = 0
        solve_config.enum_mode = mode.value if isinstance(mode, RefinementMode) else "auto"
        if ignore_optimization:
            # Stated here; optimize_iter states its own opt_mode on every
            # entry, so an ignore never leaks into a later optimize
            solve_config.opt_mode = "ignore"
        return converted

    def abandon(self) -> None:
        """
        Close the previous solve's result if it is still open, freeing this
        grounding for the next solve() — useful when the old result is no
        longer in hand. Idempotent; a no-op if nothing is open.

        Only a SUSPENDED search can be closed: if the previous solve is
        executing right now (in another thread), this raises with the
        remedies instead of silently failing to free the grounding.
        """
        with self._solve_lock:
            if self._active is not None:
                # An executing search raises close()'s teaching RuntimeError
                # (interrupt or timeout), leaving it active
                self._active.close()
                self._active = None

    def solve(
        self,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        ignore_optimization: bool = False,
    ) -> SolveResult:
        """
        Solve this grounding, returning a SolveResult that yields Models lazily.

        The stream is unbounded: take what you need (next(iter(result)) for
        one model, itertools.islice for N, a for-loop with break for a
        condition) — clasp computes the next model only when you resume, so
        nothing runs ahead of your consumption. Whole-stream reads
        (list(result), a bare for-loop) enumerate EVERY model, which an
        underconstrained program can make effectively endless.

        Args:
            timeout: Wall-clock limit in seconds (0 for no limit), counted
                from the start of iteration.
            assumptions: Atoms fixed for THIS solve only — a grounded
                Predicate assumes it true, ~Predicate assumes it false
                (assumptions are solver literals, so ~ is exact). Each atom
                must occur in this grounding: assuming an absent atom would
                silently make every model vanish (or be vacuous), so an
                unknown atom raises instead.
            ignore_optimization: Enumerate answer sets as if the program had
                no #minimize/#maximize (clasp's opt_mode=ignore): every
                answer set streams, no cost is computed. For THIS solve
                only; a later optimize() on this grounding still optimizes.
                Requires an objective to ignore — on a program without one,
                this flag raises instead of passing vacuously.
        """
        with self._solve_lock:
            converted = self._begin_solve(None, timeout, assumptions, ignore_optimization)
            self._active = result = SolveResult(
                self._control,
                self._predicate_types,
                timeout,
                self._message_handler,
                assumptions=converted,
                hidden_classes=self._hidden_classes,
            )
        return result

    def cautious_iter(
        self,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        ignore_optimization: bool = False,
    ) -> RefinementSteps:
        """
        The iterator form of cautious() — findall/finditer, eager/lazy.
        Iterate for successive approximations (claim-free AtomCollections)
        shrinking toward the intersection, and stop whenever your question
        is answered, e.g. the atom you care about has dropped out
        (certified not-forced). Each step is a full solver search, so
        control between steps is control over real work. See
        RefinementSteps for the full contract; ignore_optimization as on
        cautious().
        """
        return self._refine_iter(RefinementMode.CAUTIOUS, timeout, assumptions, ignore_optimization)

    def brave_iter(
        self,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        ignore_optimization: bool = False,
    ) -> RefinementSteps:
        """
        The iterator form of brave() — findall/finditer, eager/lazy.
        Iterate for successive approximations (claim-free AtomCollections)
        growing toward the union, every atom certified possible as it
        arrives; stop whenever your question is answered. See
        RefinementSteps for the full contract; ignore_optimization as on
        brave().
        """
        return self._refine_iter(RefinementMode.BRAVE, timeout, assumptions, ignore_optimization)

    def _refine_iter(
        self,
        mode: RefinementMode,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        ignore_optimization: bool = False,
    ) -> RefinementSteps:
        with self._solve_lock:
            converted = self._begin_solve(mode, timeout, assumptions, ignore_optimization)
            self._active = steps = RefinementSteps(
                self._control,
                self._predicate_types,
                timeout,
                self._message_handler,
                converted,
                mode,
                hidden_classes=self._hidden_classes,
            )
        return steps

    def cautious(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        ignore_optimization: bool = False,
    ) -> CautiousConsequences | None:
        """
        The atoms true in EVERY answer set (the intersection) — "which cells
        are forced" is this question. Eager sugar over cautious_iter().
        Returns None if the program is unsatisfiable. To learn WHICH
        assumptions conflicted, use the iterator twin: exhaust
        cautious_iter(assumptions=...) and read unsat_core off the handle.

        timeout (seconds) and max_iterations (refinement steps) each bound
        the work, 0 meaning unbounded; a bounded run returns an INCOMPLETE
        result (complete=False), from which absence is still certified —
        see CautiousConsequences. A timeout before the first approximation
        raises TimeoutError (nothing representable yet). Raises ValueError
        if the program optimizes: the refinement would aggregate the
        cost-descent path, not the optima — pass ignore_optimization=True
        to refine over ALL answer sets as if there were no objective
        (clasp's opt_mode=ignore, for THIS search only). The flag requires
        an objective to ignore, like solve()'s.
        """
        return self._refine_eagerly(
            RefinementMode.CAUTIOUS, CautiousConsequences, timeout, max_iterations, assumptions, ignore_optimization
        )

    def brave(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        ignore_optimization: bool = False,
    ) -> BraveConsequences | None:
        """
        The atoms true in AT LEAST ONE answer set (the union) — "which cells
        are possible" is this question. Eager sugar over brave_iter().
        Returns None if the program is unsatisfiable. To learn WHICH
        assumptions conflicted, use the iterator twin: exhaust
        brave_iter(assumptions=...) and read unsat_core off the handle.

        timeout (seconds) and max_iterations (refinement steps) each bound
        the work, 0 meaning unbounded; a bounded run returns an INCOMPLETE
        result (complete=False) whose every atom is still certified
        possible — see BraveConsequences. Raises ValueError if the program
        optimizes, unless ignore_optimization=True (see cautious()).
        """
        return self._refine_eagerly(
            RefinementMode.BRAVE, BraveConsequences, timeout, max_iterations, assumptions, ignore_optimization
        )

    def optimize_iter(
        self,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        strategy: OptStrategy = OptStrategy.BB,
        all_optima: bool = False,
        bound: int | Mapping[int, int] | None = None,
    ) -> OptimizeSteps:
        """
        The iterator form of optimize().
        Iterate for strictly-better answer sets (CostedModels) and stop
        whenever the current best is good enough: every emission is a
        genuine solution, so early exit keeps a usable answer (the
        anytime workflow). See OptimizeSteps for the full contract.

        strategy selects clasp's optimization algorithm — see OptStrategy;
        under USC the stream may be just the final optimum. With
        all_optima the stream continues past the optimality proof and
        re-emits EVERY optimal model, certified (.proven True) — filter
        on .proven for just the certified ones. bound starts the search
        from a known cost: a bare int for a single-tier program, or a
        {priority: value} mapping keyed by priority (required with
        multiple tiers). Keys are applied best-effort — the longest
        leading prefix of the surviving tiers (see optimization_levels;
        clasp bounds are positional from the highest tier) — and the
        rest, dead tiers and typos alike, are silently ignored: a
        dropped key costs pruning, and clasp compares the WHOLE cost
        tuple lexicographically against the applied bounds, not tier by
        tier. An APPLIED bound changes what comes back when it bites:
        only models at or below it are considered, so a too-tight bound
        is reported as unsatisfiable (None) — clasp cannot tell the
        difference. A maximization's bound lives in NEGATED-cost space
        like everything else about its cost: to accept totals of at
        least 9, pass bound=-9.
        """
        items: dict[int, int] | None = None
        if bound is not None and isinstance(bound, Mapping):
            items = dict(bound)
            if not items:
                # An empty mapping states "no bounds", exactly like None
                items = None
                bound = None
            elif not all(isinstance(v, int) and not isinstance(v, bool) for pair in items.items() for v in pair):
                raise TypeError(f"priority-keyed bounds must map int priorities to int bounds, got {bound!r}")
        elif bound is not None and (isinstance(bound, bool) or not isinstance(bound, int)):
            # Positional lists are deliberately unsupported: their meaning
            # silently shifts when a declared tier grounds empty
            raise TypeError(
                f"bound must be an int (single-tier programs) or a {{priority: bound}} mapping, got {bound!r}"
            )
        candidates = list(items.values()) if items is not None else ([bound] if isinstance(bound, int) else [])
        for b in candidates:
            if not -(2**63) <= b < 2**63:
                raise ValueError(
                    f"bound value {b} is outside clasp's 64-bit cost range [-9223372036854775808, 9223372036854775807]"
                )
        with self._solve_lock:
            return self._locked_optimize_iter(timeout, assumptions, strategy, all_optima, items, bound)

    def _locked_optimize_iter(
        self,
        timeout: float,
        assumptions: Sequence[Predicate | DefaultNegation] | None,
        strategy: OptStrategy,
        all_optima: bool,
        items: Mapping[int, int] | None,
        bound: int | Mapping[int, int] | None,
    ) -> OptimizeSteps:
        """The body of optimize_iter, under the sequential-solve lock."""
        converted = self._begin_solve(OPTIMIZE, timeout, assumptions)
        bounds: list[int] = []
        if items is not None:
            # A bound is a pruning hint, not a semantic constraint: the
            # optimum is the same with or without it. So keys are applied
            # best-effort against gringo's surviving levels — the longest
            # leading prefix they cover (clasp bounds are positional from
            # the highest tier) — and everything else drops silently:
            # a key on a dead tier, a typo, or an inexpressible trailing
            # bound costs search time, never correctness
            for level in self._ground_levels:
                if level not in items:
                    break
                bounds.append(items[level])
        elif isinstance(bound, int):
            # A bare int is only unambiguous when exactly one tier survived
            if len(self._ground_levels) != 1:
                raise ValueError(
                    f"a bare int bound is ambiguous here (surviving tiers "
                    f"{list(self._ground_levels)}); name the tier: bound={{priority: value}}."
                )
            bounds = [bound]
        solve_config = self._control.configuration.solve
        assert isinstance(solve_config, clingo.Configuration)
        # Stated on every entry: optN re-emits certified optima after the
        # proof; a bound rides along as clasp's initial cost ceiling
        opt_mode = "optN" if all_optima else "opt"
        if bounds:
            opt_mode += "," + ",".join(str(b) for b in bounds)
        solve_config.opt_mode = opt_mode
        solver_config = self._control.configuration.solver
        assert isinstance(solver_config, clingo.Configuration)
        # Stated on every entry, like enum_mode: the strategy is per-solve
        solver_config.opt_strategy = strategy.value
        self._active = steps = OptimizeSteps(
            self._control,
            self._predicate_types,
            timeout,
            self._message_handler,
            converted,
            hidden_classes=self._hidden_classes,
        )
        return steps

    def optimize(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
        strategy: OptStrategy = OptStrategy.BB,
        all_optima: bool = False,
        bound: int | Mapping[int, int] | None = None,
    ) -> Optimum | None:
        """
        The best answer set by the program's objectives. Eager sugar over
        optimize_iter(). Returns None if the program is unsatisfiable —
        or, with bound=, if no model exists within the bound (clasp
        reports the two identically). To learn WHICH assumptions
        conflicted, use the iterator twin: exhaust
        optimize_iter(assumptions=...) and read unsat_core off the
        handle. strategy selects clasp's algorithm
        (see OptStrategy: USC can be night-and-day faster when branch and
        bound stalls).

        With all_optima the search continues past the optimality proof
        and the result's .optima holds EVERY certified optimal model
        (len 1 answers uniqueness); without it, .optima is None and the
        descent is still available as .path.

        timeout (seconds) and max_iterations (emissions) each bound the
        work, 0 meaning unbounded; a bounded run returns the best model
        FOUND SO FAR with proven=False — a genuine solution, just not a
        proven optimum. Raises TimeoutError only when the deadline lands
        before any model at all (no best-so-far exists to return), and
        ValueError if the program has no objective.
        """
        _validate_max_iterations(max_iterations)
        steps = self.optimize_iter(timeout, assumptions, strategy, all_optima=all_optima, bound=bound)
        path: list[CostedModel] = []
        complete = False
        try:
            for model in steps:
                path.append(model)
                if max_iterations and len(path) >= max_iterations:
                    # Even a cap landing exactly on the optimum reports
                    # unproven: the proof of optimality never ran
                    break
            else:
                complete = steps.exhausted
        finally:
            steps.close()
        if not path:
            # A timeout before any model raised from the iteration itself;
            # reaching here empty-handed means the search exhausted
            return None  # unsatisfiable (or nothing within the bound)
        certified = [model for model in path if model.proven]
        best = certified[0] if certified else path[-1]
        return Optimum(
            atoms=best.atoms(),
            cost=best.cost,
            path=tuple(path),
            # A certificate proves the best directly; a plain search's
            # proof is exhaustion (its emissions are never certified)
            proven=bool(certified) or (not all_optima and complete),
            messages=steps.messages,
            optima=tuple(certified) if all_optima else None,
            complete=complete,
            statistics=steps.statistics,
            # The cost tuple has one entry per surviving level, highest
            # first — the same order optimization_levels reports
            levels=dict(zip(self._ground_levels, best.cost, strict=True)),
            timed_out=steps.timed_out,
            hidden_classes=self._hidden_classes,
        )

    def _refine_eagerly[C: Consequences](
        self,
        mode: RefinementMode,
        result_class: type[C],
        timeout: float,
        max_iterations: int,
        assumptions: Sequence[Predicate | DefaultNegation] | None,
        ignore_optimization: bool = False,
    ) -> C | None:
        """
        The shared fold under cautious()/brave(): consume the steps
        primitive, honoring the bounds, and build the injected result
        class from the fold — its path is every approximation in order
        (the last is the headline answer) and its complete is True only
        when the refinement PROVED exhaustion (False whenever a bound cut
        it short, including a cap landing exactly on the final step).
        Returns None for proven unsatisfiability.
        """
        _validate_max_iterations(max_iterations)
        steps = self._refine_iter(mode, timeout, assumptions, ignore_optimization)
        path: list[AtomCollection] = []
        complete = False
        try:
            for approximation in steps:
                path.append(approximation)
                if max_iterations and len(path) >= max_iterations:
                    # Even a cap landing exactly on the final approximation
                    # reports incomplete: exhaustion was never proven
                    break
            else:
                complete = steps.exhausted
        except TimeoutError:
            if mode is RefinementMode.CAUTIOUS and not path:
                raise TimeoutError(
                    "cautious refinement was interrupted before its first approximation; "
                    "with no models seen, its superset bound is every atom — nothing "
                    "representable to return. Raise the timeout."
                ) from None
        finally:
            steps.close()
        if not path and complete:
            return None  # proved unsatisfiable: no answer sets to ask about
        return result_class(
            atoms=list(path[-1].atoms()) if path else [],
            path=tuple(path),
            complete=complete,
            messages=steps.messages,
            timed_out=steps.timed_out,
            statistics=steps.statistics,
            hidden_classes=self._hidden_classes,
        )
