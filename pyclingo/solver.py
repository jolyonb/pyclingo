import math
from collections.abc import Mapping, Sequence

import clingo

from pyclingo.choice import Choice
from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel
from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.conditioned_element import CONDITION_TYPE
from pyclingo.core import DefaultNegation, DefinedConstant, PredicateOccurrence, Term
from pyclingo.optimization import OPTIMIZATION_TERM_TYPE, OptStrategy
from pyclingo.predicate import NegatedPredicate, Predicate
from pyclingo.program_elements import RawASP
from pyclingo.scoping import validate_rule
from pyclingo.segment import Segment, When
from pyclingo.solve_result import (
    OPTIMIZE,
    SEARCH_MODE,
    AtomCollection,
    BraveConsequences,
    CautiousConsequences,
    Consequences,
    CostedModel,
    OptimizeSteps,
    Optimum,
    RefinementMode,
    RefinementSteps,
    SearchABC,
    SolveResult,
    convert_predicate_to_symbol,
)
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


class ASPProgram:
    """
    Represents a complete ASP program.

    This class manages a collection of rules, comments, and other elements
    that make up an ASP program, and provides methods to build and render
    the program.
    """

    def __init__(
        self, header: str | None = None, default_segment: str = "Rules", allow_singletons: bool = False
    ) -> None:
        """
        Initialize an empty ASP program.

        allow_singletons switches off the singleton-variable lint (a variable
        used exactly once is rejected as a likely typo). The lint is
        pyclingo-only — gringo is silent about singletons — so exploratory
        code may prefer it off; ANY remains the per-variable escape either
        way. Safety checks are not affected.
        """
        if header is not None and ("\n" in header or "\r" in header):
            raise ValueError("Program header must be a single line (it renders as one % comment)")
        self._check_singletons = not allow_singletons
        self._segments: dict[str, Segment] = {}
        self._defined_constants: dict[str, int | str] = {}
        self._show_overrides: dict[type[Predicate], bool] = {}
        # When True, solution identity is the SHOWN atoms: models agreeing on
        # every shown atom count as one (clingo's solve.project=show), so
        # hidden helper predicates stop multiplying models.
        self.project_shown: bool = False
        # Conditional shows are per SIGN: (class, negated) -> the directive's
        # conditional literal. Each sign's visibility resolves independently:
        # its conditional override, else the class's bool override/default.
        self._show_when_overrides: dict[tuple[type[Predicate], bool], ConditionalLiteral] = {}
        self.header: str | None = header
        self.default_segment: str = Segment.validate_name(default_segment)

    def _default_segment(self) -> Segment:
        """The default segment, created on first use; every other segment needs add_segment."""
        key = self.default_segment
        if key not in self._segments:
            self._segments[key] = Segment(key, allow_singletons=not self._check_singletons)
        return self._segments[key]

    def __getitem__(self, segment: str) -> Segment:
        """
        The named segment. Reading never creates: an unknown name raises
        KeyError naming the existing segments (add_segment is the one
        creation point; the default segment self-creates on first write).
        """
        key = Segment.validate_name(segment)
        if key not in self._segments:
            existing = ", ".join(f"'{name}'" for name in self._segments) or "none"
            raise KeyError(f"Segment '{segment}' does not exist; existing segments: {existing}")
        return self._segments[key]

    def __setitem__(self, segment: str, value: Segment) -> None:
        """
        Assign a segment, dict-style: a new name appends, an existing
        name REPLACES the segment with its rendering position preserved.
        The segment's own name must match the key: names are never
        rebound.
        """
        key = Segment.validate_name(segment)
        if not isinstance(value, Segment):
            raise TypeError(f"Expected a Segment, got {type(value).__name__}")
        if value.name != key:
            raise ValueError(
                f"Key '{key}' does not match the segment's name '{value.name}'; "
                f"names are never rebound — construct the Segment with the name you mean"
            )
        self._segments[key] = value

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
            segment if isinstance(segment, Segment) else Segment(segment, allow_singletons=not self._check_singletons)
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
        key = Segment.validate_name(segment)
        if key not in self._segments:
            existing = ", ".join(f"'{name}'" for name in self._segments) or "none"
            raise KeyError(f"Segment '{segment}' does not exist; existing segments: {existing}")
        del self._segments[key]

    def fact(self, *facts: Predicate | Choice) -> None:
        """Add unconditional statements to the default segment; see Segment.fact()."""
        self._default_segment().fact(*facts)

    def when(self, *conditions: Term) -> When:
        """Hold conditions for a closer, in the default segment; see Segment.when()."""
        return self._default_segment().when(*conditions)

    def forbid(self, *conditions: Term) -> None:
        """Forbid the combination, in the default segment; see Segment.forbid()."""
        self._default_segment().forbid(*conditions)

    def require(self, *comparison: Term) -> None:
        """Require a comparison to hold, in the default segment; see Segment.require()."""
        self._default_segment().require(*comparison)

    def minimize(
        self,
        weight: int | OPTIMIZATION_TERM_TYPE,
        *tuple_terms: OPTIMIZATION_TERM_TYPE,
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None = None,
        priority: int = 0,
    ) -> None:
        """Add a #minimize statement to the default segment; see Segment.minimize()."""
        self._default_segment().minimize(weight, *tuple_terms, condition=condition, priority=priority)

    def maximize(
        self,
        weight: int | OPTIMIZATION_TERM_TYPE,
        *tuple_terms: OPTIMIZATION_TERM_TYPE,
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None = None,
        priority: int = 0,
    ) -> None:
        """Add a #maximize statement to the default segment; see Segment.maximize()."""
        self._default_segment().maximize(weight, *tuple_terms, condition=condition, priority=priority)

    def penalize(
        self,
        *conditions: Term,
        weight: int | OPTIMIZATION_TERM_TYPE = 1,
        terms: Sequence[OPTIMIZATION_TERM_TYPE] | None = None,
        priority: int = 0,
    ) -> None:
        """Charge for each match of the conditions, in the default segment; see Segment.penalize()."""
        self._default_segment().penalize(*conditions, weight=weight, terms=terms, priority=priority)

    def raw_asp(self, text: str, predicates: Sequence[type[Predicate] | NegatedPredicate] = ()) -> None:
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

    def define_constant(self, name: str, value: int | str) -> DefinedConstant:
        """
        Define a #const constant, rendered as "#const name = value.".

        Raises:
            ValueError: If the name is invalid or already defined.
        """
        if not isinstance(name, str):
            raise TypeError(f"Constant name must be a string, got {type(name).__name__}")
        if isinstance(value, int) and not isinstance(value, bool) and not -(2**31) <= value < 2**31:
            raise ValueError(
                f"Constant value {value} is outside clingo's integer range "
                f"[-2147483648, 2147483647]; clingo would silently wrap it"
            )
        if not name.isascii():
            raise ValueError(f"Constant name must be ASCII (gringo's lexer is ASCII-only): {name!r}")
        if not name or not name[0].islower():
            raise ValueError(f"Constant name must start with a lowercase letter: {name}")
        if name == "not":
            raise ValueError("'not' is reserved in ASP and cannot be a constant name")

        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Constant name can only contain letters, digits, and underscores: {name}")

        if name in self._defined_constants:
            raise ValueError(f"Defined constant '{name}' is already registered")

        if isinstance(value, bool) or not isinstance(value, (int, str)):
            # bool subclasses int, and a boolean is never a valid ASP term
            raise TypeError(f"Constant value must be an integer or string, got {type(value).__name__}")
        if isinstance(value, str) and any(c in value for c in ('"', "\\", "\n", "\r")):
            raise ValueError(f"Constant string value cannot contain quotes, backslashes, or newlines: {value!r}")

        self._defined_constants[name] = value

        return DefinedConstant(name)

    def show(self, predicate: type[Predicate]) -> None:
        """
        Show this predicate in output, overriding its default visibility.

        Showing a predicate the program never derives is an error at render
        when it is provably absent; if the atoms come from a raw_asp() block,
        the check cannot see them, and an absent signature instead fails at
        solve with gringo's "no atoms over signature" info.
        """
        self._show_overrides[predicate] = True

    def hide(self, predicate: type[Predicate]) -> None:
        """
        Hide this predicate from output, overriding its default visibility.

        Hiding a class that only ever appears nested inside other atoms is
        vacuous: argument-position data cannot be hidden, and no error is
        raised (hide states an intent; show() of an underived class errors
        because it states an expectation).
        """
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
        call order (resolution is by kind, not time), and there is no
        way to unregister one.
        """
        if not isinstance(condition, ConditionalLiteral):
            raise TypeError(f"show_when condition must be a ConditionalLiteral, got {type(condition).__name__}")
        head = condition.head
        if not isinstance(head, Predicate):
            raise ValueError(
                f"show_when needs a conditional literal whose head is a predicate atom "
                f"(the thing to show), got {type(head).__name__}"
            )
        # A show directive is a capture too: freeze so later mutation of a
        # shared builder cannot silently rewrite it, and validate its variables
        # (a #show directive has no rule body, so everything must be bound
        # inside the conditional literal itself)
        validate_rule(None, [condition], f"#show {condition.render()}.", check_singletons=self._check_singletons)
        condition.freeze()
        self._show_when_overrides[(type(head), head.negated)] = condition

    def _collect_predicates(self) -> set[type[Predicate]]:
        """
        Every predicate class the program knows, by ANY door: segment
        elements, show_when conditions, and show()/hide() overrides. This
        set is the reconstruction registry and the declaration universe
        for the raw_asp contract — naming a class to show() declares it
        as fully as predicates= does, because the class object itself is
        what a declaration provides.
        """
        return {cls for cls, _negated, _is_atom in self._collect_predicate_occurrences()} | set(self._show_overrides)

    def _collect_predicate_occurrences(self) -> set[PredicateOccurrence]:
        """(class, negated, is_atom) occurrences across the whole program."""
        occurrences: set[PredicateOccurrence] = set()
        for segment in self._segments.values():
            occurrences.update(segment.collect_predicate_occurrences())
        for condition in self._show_when_overrides.values():
            occurrences.update(condition.collect_predicate_occurrences(as_argument=False))
        return occurrences

    def _has_raw_asp(self) -> bool:
        """Whether any segment contains a RawASP block (raw text is invisible to the tree walkers)."""
        return any(isinstance(element, RawASP) for segment in self._segments.values() for element in segment)

    def _validate_shown_predicates(self) -> None:
        """
        Raise for show()/show_when() of atoms nothing derives — but only when
        the program has no raw_asp blocks: raw text is invisible to the
        walkers, so with raw blocks present an uncollected predicate may
        still be derived (that is what raw_asp's predicates= is for).
        """
        if self._has_raw_asp():
            return
        # Derivation evidence comes from the program's own rules: a show_when
        # condition's atoms must not vouch for themselves
        atom_occurrences = {
            (cls, negated)
            for segment in self._segments.values()
            for cls, negated, is_atom in segment.collect_predicate_occurrences()
            if is_atom
        }
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

    def _validate_names(self) -> None:
        """
        Raise on naming collisions that would corrupt solving:

        - two distinct predicate classes sharing (name, arity): solutions could not
          be reconstructed unambiguously
        - a nullary predicate sharing its name with a #const: gringo substitutes
          the constant only in TERM positions, so the atom stays a distinct,
          silently unrelated symbol
        """
        by_signature: dict[tuple[str, int], type[Predicate]] = {}
        for pred in self._collect_predicates():
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
                    f"classes ({other.__name__} and {pred.__name__}); solutions cannot be "
                    f"reconstructed unambiguously. Give one a namespace in Predicate.define()."
                )
            by_signature[key] = pred

    def render(self) -> str:
        """
        Render the complete ASP program, in order:

        1. Header comments
        2. #const definitions (only those actually used)
        3. Program segments (rules, comments, section headers)
        4. #show directives (program overrides, then class defaults)
        """
        for segment in self._segments.values():
            segment.check_pending()
        self._validate_constants()
        self._validate_names()
        self._validate_shown_predicates()

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
            else:
                lines.append(f"#const {name} = {value}.")  # Integer values are not

        # 3. Program segments: headers only when more than one segment exists,
        # with a blank line between rendered segments (none before the first)
        with_headers = len(self._segments) > 1
        first_segment = True
        for segment in self._segments.values():
            if len(segment) == 0:
                continue
            if with_headers and not first_segment:
                lines.append("")
            first_segment = False
            lines.append(segment.render(with_header=with_headers))

        # 4. #show directives: program overrides first, class defaults second.
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
        # included) — the same evidence validation uses, so a show_when
        # condition can never vouch a dangling directive past the check
        occurrences = {occ for segment in self._segments.values() for occ in segment.collect_predicate_occurrences()}
        walked_positive = {cls for cls, negated, is_atom in occurrences if is_atom and not negated}
        has_raw = self._has_raw_asp()
        override_positive = {
            cls
            for cls, visibility in self._show_overrides.items()
            if visibility is True and (cls in walked_positive or has_raw)
        }
        positive_classes = walked_positive | override_positive
        negated_classes = {cls for cls, negated, is_atom in occurrences if is_atom and negated}
        all_classes = (
            self._collect_predicates() | set(self._show_overrides) | {cls for cls, _ in self._show_when_overrides}
        )
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
            lines.extend(("", "#show."))
            lines.extend(sorted(show_statements))

        return "\n".join(lines) + "\n"

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

    def ground(self, stop_on_log_level: LogLevel = LogLevel.INFO) -> GroundedProgram:
        """
        Render and ground the program once, returning a handle that can be
        solved repeatedly — the re.compile() of this API. solve() is sugar
        for ground().solve(); use ground() directly when the same program
        will be solved many times (grounding is the expensive step).

        The handle is an independent snapshot — it holds the rendered text
        and solves exactly that program forever, like a compiled regex holds
        its pattern. Mutating this ASPProgram afterwards does not affect
        existing handles; ground() again for the updated program (keeping
        both handles is fine, e.g. to compare a program with and without a
        rule).

        Raises:
            ValueError: For render-time validation failures (undeclared
                constants, name collisions, shows of underived predicates)
            RuntimeError: If an error occurs during parsing or grounding, or
                the log level threshold is exceeded
        """
        asp_source = self.render()

        message_handler = ClingoMessageHandler(asp_source, stop_on_level=stop_on_log_level)
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
            raise RuntimeError(error_msg) from e

        try:
            control.ground([("base", [])])
        except RuntimeError as e:
            error_msg = f"Grounding failed: {e}\n\n"
            if formatted_messages := message_handler.format_all_messages(verb="grounding"):
                error_msg += formatted_messages
            raise RuntimeError(error_msg) from e

        # Messages below the stop threshold are tolerated silently; at or above
        # it, the full formatted diagnostics ride along in the raised error
        if message_handler.should_halt:
            assert message_handler.highest_level is not None
            raise RuntimeError(
                f"Grounding produced {message_handler.highest_level.name} level messages "
                f"(stop threshold: {stop_on_log_level.name}).\n\n"
                f"{message_handler.format_all_messages(verb='grounding')}"
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

        predicate_types = {(pred.get_name(), pred.get_arity()): pred for pred in self._collect_predicates()}

        # Raw text is invisible to the walkers, so with raw blocks present
        # the raw_asp contract (exhaustive declaration) is enforced here,
        # against gringo's own signature table: every ground signature must
        # be a declared class.
        if self._has_raw_asp():
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
        )

    def solve(self, timeout: float = 0, stop_on_log_level: LogLevel = LogLevel.INFO) -> SolveResult:
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
            stop_on_log_level: Log level at which to abort — applies to parsing
                and grounding. Solve-phase messages never halt; they are
                captured on each Model (.messages) and the SolveResult

        Returns:
            A SolveResult: iterate it for Models (each with typed atoms() access);
            its satisfiable/exhausted/solution_count/statistics finalize when
            iteration ends on any path (exhaustion, close(), or a with-block).

        Raises:
            ValueError: For render-time validation failures (undeclared
                constants, name collisions, shows of underived predicates)
            RuntimeError: If an error occurs during parsing or grounding, or the
                log level threshold is exceeded

        Notes:
            Rendering, grounding, and their error checks run eagerly at this call; only
            model enumeration is lazy. Every call returns an independent SolveResult,
            so repeated solves on one program never interfere.
        """
        return self.ground(stop_on_log_level=stop_on_log_level).solve(timeout=timeout)

    def cautious(
        self, timeout: float = 0, max_iterations: int = 0, stop_on_log_level: LogLevel = LogLevel.INFO
    ) -> CautiousConsequences | None:
        """The atoms true in every answer set; sugar for ground().cautious(). See GroundedProgram.cautious()."""
        return self.ground(stop_on_log_level=stop_on_log_level).cautious(timeout=timeout, max_iterations=max_iterations)

    def brave(
        self, timeout: float = 0, max_iterations: int = 0, stop_on_log_level: LogLevel = LogLevel.INFO
    ) -> BraveConsequences | None:
        """The atoms true in at least one answer set; sugar for ground().brave(). See GroundedProgram.brave()."""
        return self.ground(stop_on_log_level=stop_on_log_level).brave(timeout=timeout, max_iterations=max_iterations)

    def optimize(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        strategy: OptStrategy = OptStrategy.BB,
        all_optima: bool = False,
        bound: int | Mapping[int, int] | None = None,
        stop_on_log_level: LogLevel = LogLevel.INFO,
    ) -> Optimum | None:
        """The best answer set by the objectives; sugar for ground().optimize(). See GroundedProgram.optimize()."""
        return self.ground(stop_on_log_level=stop_on_log_level).optimize(
            timeout=timeout, max_iterations=max_iterations, strategy=strategy, all_optima=all_optima, bound=bound
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
        defined_constants: dict[str, int | str] | None = None,
        ground_levels: tuple[int, ...] = (),
    ) -> None:
        self._text = text
        self._control = control
        self._predicate_types = predicate_types
        self._message_handler = message_handler
        self._defined_constants = defined_constants or {}
        # Ground truth from the minimize observer: the surviving priority
        # levels, highest first — bool(levels) IS "does this program optimize?"
        self._ground_levels = ground_levels
        self._active: SearchABC | None = None

    @property
    def text(self) -> str:
        """The rendered ASP program this grounding solves."""
        return self._text

    @property
    def optimization_levels(self) -> tuple[int, ...]:
        """
        The SURVIVING optimization priority levels, highest first — ground
        truth from gringo (a declared tier whose elements ground empty is
        absent). Empty means the program does not optimize. Cost tuples
        and bounds follow these levels.
        """
        return self._ground_levels

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
        mode: SEARCH_MODE,
        timeout: float,
        assumptions: Sequence[Predicate | DefaultNegation] | None,
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
        if timeout < 0 or math.isnan(timeout):
            raise ValueError(f"timeout must be non-negative, got {timeout}")
        if self._ground_levels and mode is None:
            raise ValueError("This program optimizes (#minimize/#maximize present). Solve it with optimize().")
        if self._ground_levels and isinstance(mode, RefinementMode):
            raise ValueError(
                f"{mode.value} consequences over an optimizing program are computed "
                f"against the solver's cost-descent path, not the set of optimal "
                f"models — the result would be wrong. Remove the optimization "
                f"directive to ask about all answer sets."
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
        return converted

    def abandon(self) -> None:
        """
        Close the previous solve's result if it is still open, freeing this
        grounding for the next solve() — useful when the old result is no
        longer in hand. Idempotent; a no-op if nothing is open.
        """
        if self._active is not None:
            self._active.close()
            self._active = None

    def solve(
        self,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
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
        """
        converted = self._begin_solve(None, timeout, assumptions)
        self._active = result = SolveResult(
            self._control,
            self._predicate_types,
            timeout,
            self._message_handler,
            assumptions=converted,
        )
        return result

    def cautious_iter(
        self, timeout: float = 0, assumptions: Sequence[Predicate | DefaultNegation] | None = None
    ) -> RefinementSteps:
        """
        The iterator form of cautious() — findall/finditer, eager/lazy.
        Iterate for successive approximations (claim-free AtomCollections)
        shrinking toward the intersection, and stop whenever your question
        is answered, e.g. the atom you care about has dropped out
        (certified not-forced). Each step is a full solver search, so
        control between steps is control over real work. See
        RefinementSteps for the full contract.
        """
        return self._refine_iter(RefinementMode.CAUTIOUS, timeout, assumptions)

    def brave_iter(
        self, timeout: float = 0, assumptions: Sequence[Predicate | DefaultNegation] | None = None
    ) -> RefinementSteps:
        """
        The iterator form of brave() — findall/finditer, eager/lazy.
        Iterate for successive approximations (claim-free AtomCollections)
        growing toward the union, every atom certified possible as it
        arrives; stop whenever your question is answered. See
        RefinementSteps for the full contract.
        """
        return self._refine_iter(RefinementMode.BRAVE, timeout, assumptions)

    def _refine_iter(
        self,
        mode: RefinementMode,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
    ) -> RefinementSteps:
        converted = self._begin_solve(mode, timeout, assumptions)
        self._active = steps = RefinementSteps(
            self._control,
            self._predicate_types,
            timeout,
            self._message_handler,
            converted or [],
            mode,
        )
        return steps

    def cautious(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
    ) -> CautiousConsequences | None:
        """
        The atoms true in EVERY answer set (the intersection) — "which cells
        are forced" is this question. Eager sugar over cautious_iter().
        Returns None if the program is unsatisfiable.

        timeout (seconds) and max_iterations (refinement steps) each bound
        the work, 0 meaning unbounded; a bounded run returns an INCOMPLETE
        result (complete=False), from which absence is still certified —
        see CautiousConsequences. A timeout before the first approximation
        raises TimeoutError (nothing representable yet). Raises ValueError
        if the program optimizes: the refinement would aggregate the
        cost-descent path, not the optima.
        """
        return self._refine_eagerly(RefinementMode.CAUTIOUS, CautiousConsequences, timeout, max_iterations, assumptions)

    def brave(
        self,
        timeout: float = 0,
        max_iterations: int = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
    ) -> BraveConsequences | None:
        """
        The atoms true in AT LEAST ONE answer set (the union) — "which cells
        are possible" is this question. Eager sugar over brave_iter().
        Returns None if the program is unsatisfiable.

        timeout (seconds) and max_iterations (refinement steps) each bound
        the work, 0 meaning unbounded; a bounded run returns an INCOMPLETE
        result (complete=False) whose every atom is still certified
        possible — see BraveConsequences. Raises ValueError if the program
        optimizes (see cautious()).
        """
        return self._refine_eagerly(RefinementMode.BRAVE, BraveConsequences, timeout, max_iterations, assumptions)

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
            if not items or not all(
                isinstance(v, int) and not isinstance(v, bool) for pair in items.items() for v in pair
            ):
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
            converted or [],
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
        reports the two identically). strategy selects clasp's algorithm
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
        if max_iterations < 0:
            raise ValueError(f"max_iterations must be non-negative (0 means unbounded), got {max_iterations}")
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
        )

    def _refine_eagerly[C: Consequences](
        self,
        mode: RefinementMode,
        result_class: type[C],
        timeout: float,
        max_iterations: int,
        assumptions: Sequence[Predicate | DefaultNegation] | None,
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
        if max_iterations < 0:
            raise ValueError(f"max_iterations must be non-negative (0 means unbounded), got {max_iterations}")
        steps = self._refine_iter(mode, timeout, assumptions)
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
        )
