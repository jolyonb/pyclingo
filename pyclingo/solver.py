from collections import defaultdict
from collections.abc import Sequence

import clingo

from pyclingo.choice import Choice
from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel
from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.conditioned_element import CONDITION_TYPE
from pyclingo.core import AtomSign, Comparison, DefaultNegation, DefinedConstant, Pool, Term
from pyclingo.optimization import (
    OPTIMIZATION_TERM_TYPE,
    Optimization,
    OptimizationDirective,
    raw_text_optimizes,
)
from pyclingo.predicate import Predicate
from pyclingo.program_elements import BlankLine, Comment, ProgramElement, RawASP, Rule
from pyclingo.scoping import validate_optimization_element, validate_rule
from pyclingo.solve_result import (
    AtomCollection,
    BraveConsequences,
    CautiousConsequences,
    Consequences,
    RefinementMode,
    RefinementSteps,
    SearchABC,
    SolveResult,
    convert_predicate_to_symbol,
)
from pyclingo.version import __version__


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
        self._segments: defaultdict[str, list[ProgramElement]] = defaultdict(list)
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
        self.default_segment: str = default_segment.lower()

    def _segment_key(self, segment: str | None) -> str:
        """Normalize a segment name (None means the default segment), rejecting invalid names."""
        if segment is None:
            return self.default_segment
        if not segment.strip():
            raise ValueError("Segment names cannot be empty")
        if "\n" in segment or "\r" in segment:
            raise ValueError("Segment names must be single-line (they render as section comments)")
        return segment.lower()

    def add_segment(self, segment: str) -> None:
        """
        Pre-declare an empty segment, fixing its position in the rendered output.

        Declaration is optional: writing to a new segment name (fact/when/forbid/
        comment) creates it on first use, ordered by first write. Declaring an
        already-existing segment is an error, because its position is already set
        and the request can't be honored.
        """
        normalized_segment = self._segment_key(segment)
        if normalized_segment in self._segments:
            raise ValueError(f"Segment '{segment}' already exists")
        self._segments[normalized_segment] = []

    def fact(self, *facts: Predicate | Choice, segment: str | None = None) -> None:
        """
        Add unconditional statements to the program: grounded facts, or bare
        choice rules like { a(1..3) } (whose element variables are local).
        """
        if not facts:
            raise ValueError("fact() requires at least one statement")
        for statement in facts:
            if not isinstance(statement, (Predicate, Choice)):
                raise TypeError(
                    f"fact() arguments must be Predicate or Choice instances, got {type(statement).__name__}"
                )
            if isinstance(statement, Predicate) and not statement.is_grounded:
                variables = ", ".join(sorted(statement.collect_variables()))
                raise ValueError(
                    f"fact() requires grounded predicates, but {statement.render()} contains "
                    f"variable(s) {variables}. Use when(conditions, let=...) to derive predicates."
                )
        for statement in facts:
            segment_key = self._segment_key(segment)
            self._segments[segment_key].append(Rule(head=statement, check_singletons=self._check_singletons))

    def when(self, *conditions: Term, let: Term, segment: str | None = None) -> None:
        """Create a clingo rule which sets the let term when all conditions are satisfied."""
        if not conditions:
            raise ValueError("when() requires at least one condition; use fact() for unconditional statements")
        for condition in conditions:
            if not isinstance(condition, Term):
                raise TypeError(f"when() conditions must be Terms, got {type(condition).__name__}")
        if not isinstance(let, Term):
            raise TypeError(f"when() let must be a Term, got {type(let).__name__}")
        segment_key = self._segment_key(segment)
        self._segments[segment_key].append(
            Rule(head=let, body=list(conditions), check_singletons=self._check_singletons)
        )

    def forbid(self, *conditions: Term, segment: str | None = None) -> None:
        """Creates a clingo constraint which forbids the specified combination of conditions."""
        if not conditions:
            raise ValueError("forbid() requires at least one condition")
        for condition in conditions:
            if not isinstance(condition, Term):
                raise TypeError(f"forbid() conditions must be Terms, got {type(condition).__name__}")
        segment_key = self._segment_key(segment)
        self._segments[segment_key].append(Rule(body=list(conditions), check_singletons=self._check_singletons))

    def require(self, *terms: Term, implies: Comparison | None = None, segment: str | None = None) -> None:
        """
        Require that a comparison holds: unconditionally, or as an implication.

        Two forms, both pure syntactic sugar for a forbid constraint on the
        inverse comparison:

            require(Count(C, condition=...) >= 2)                # must hold, always
            require(Clue(num=N), implies=Count(...) == N)        # conditions imply it

        The second is the material implication W -> C, entirely equivalent to
        forbid(*W, C.inverse()). Note that unlike when(), require() checks the
        relation but never derives. The implication example renders
        ":- clue(N), #count{ Adj : ... } != N."
        """
        target: Term
        conditions: tuple[Term, ...]
        if implies is None:
            if len(terms) != 1:
                raise TypeError(
                    "require() without implies= takes exactly one Comparison (the unconditional "
                    "form); to require a comparison under conditions, pass it as "
                    "require(*conditions, implies=comparison)."
                )
            # A single non-Comparison falls through to the teaching error below
            target = terms[0]
            conditions = ()
        else:
            target = implies
            conditions = terms
        if not isinstance(target, Comparison):
            raise TypeError(
                f"require() implies must be a Comparison, got {type(target).__name__}. To make "
                f"a predicate hold, derive it with when(*conditions, let=...)."
            )
        if isinstance(target.right_term, Pool):
            raise ValueError(
                "require() cannot invert a pool comparison: pools expand disjunctively, "
                "so 'X != (2;3)' is true for every X. Write the domain restriction as a "
                "positive body condition instead."
            )
        for condition in conditions:
            if not isinstance(condition, Term):
                raise TypeError(f"require() conditions must be Terms, got {type(condition).__name__}")
        self.forbid(*conditions, target.inverse(), segment=segment)

    def minimize(
        self,
        weight: int | OPTIMIZATION_TERM_TYPE,
        *tuple_terms: OPTIMIZATION_TERM_TYPE,
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None = None,
        priority: int = 0,
        segment: str | None = None,
    ) -> None:
        """
        Add a #minimize statement: among the answer sets, prefer those
        where the total weight is smallest. The weight is summed over
        DISTINCT ground tuples, so include identifying terms after it
        exactly as in a #sum tuple:

            minimize(Size, C, condition=island(loc=C, size=Size))

        renders "#minimize{ Size, C : island(C, Size) }." — without C, two
        same-sized islands would collapse to one contribution. priority
        stacks objectives lexicographically (higher decided first,
        rendered W@P); priorities are ordinal keys and gaps are free.
        All statements at a priority share ONE tuple set: duplicate
        tuples count once, distinct tuples sum.

        Every variable must be bound by the element's own conditions — this
        directive has no rule body. Optimization changes how the program
        must be solved; see optimize().
        """
        self._add_optimization(Optimization.MINIMIZE, weight, tuple_terms, condition, priority, segment)

    def maximize(
        self,
        weight: int | OPTIMIZATION_TERM_TYPE,
        *tuple_terms: OPTIMIZATION_TERM_TYPE,
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None = None,
        priority: int = 0,
        segment: str | None = None,
    ) -> None:
        """
        Add a #maximize statement: prefer answer sets with the LARGEST
        total weight. Exactly minimize() with the preference flipped
        (clingo reports the cost of a maximization as a negated sum). See
        minimize() for the tuple-distinctness and priority rules.
        """
        self._add_optimization(Optimization.MAXIMIZE, weight, tuple_terms, condition, priority, segment)

    def _add_optimization(
        self,
        sense: Optimization,
        weight: int | OPTIMIZATION_TERM_TYPE,
        tuple_terms: tuple[OPTIMIZATION_TERM_TYPE, ...],
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None,
        priority: int,
        segment: str | None,
    ) -> None:
        directive = OptimizationDirective(sense, weight, tuple_terms, condition, priority)
        validate_optimization_element(directive.element, directive.render(), check_singletons=self._check_singletons)
        directive.element.freeze()
        self._segments[self._segment_key(segment)].append(directive)

    def raw_asp(self, text: str, segment: str | None = None, predicates: Sequence[type[Predicate]] = ()) -> None:
        """
        Add a verbatim block of ASP text: the escape hatch for constructs
        pyclingo does not model.

        Declare any predicates the block produces via predicates so that show
        directives cover them and solutions round-trip into typed instances.
        """
        if not isinstance(text, str):
            raise TypeError(f"raw_asp() text must be a string, got {type(text).__name__}")
        segment_key = self._segment_key(segment)
        self._segments[segment_key].append(RawASP(text, predicates))

    def comment(self, text: str, segment: str | None = None) -> None:
        """Add a comment to the program."""
        segment_key = self._segment_key(segment)
        self._segments[segment_key].append(Comment(text))

    def blank_line(self, segment: str | None = None) -> None:
        """Add a blank line to the program for formatting."""
        segment_key = self._segment_key(segment)
        self._segments[segment_key].append(BlankLine())

    def section(self, title: str, segment: str | None = None) -> None:
        """Add a blank line and title comment as a section header."""
        self.blank_line(segment=segment)
        self.comment(title, segment=segment)

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
        """Hide this predicate from output, overriding its default visibility."""
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
        other sign falls back to the class's show()/hide()/default.
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
        """Collect all predicate classes used anywhere in the program, show_when conditions included."""
        predicates = set()

        for _segment_name, elements in self._segments.items():
            for element in elements:
                predicates.update(element.collect_predicates())

        for condition in self._show_when_overrides.values():
            predicates.update(condition.collect_predicates())

        return predicates

    def _collect_predicate_signs(self) -> set[AtomSign]:
        """(class, negated, is_atom) occurrences across the whole program."""
        signs: set[AtomSign] = set()
        for elements in self._segments.values():
            for element in elements:
                signs.update(element.collect_predicate_signs())
        for condition in self._show_when_overrides.values():
            signs.update(condition.collect_predicate_signs())
        return signs

    def _validate_shown_predicates(self) -> None:
        """
        Raise for show()/show_when() of atoms nothing derives — but only when
        the program has no raw_asp blocks: raw text is invisible to the
        walkers, so with raw blocks present an uncollected predicate may
        still be derived (that is what raw_asp's predicates= is for).
        """
        has_raw = any(isinstance(element, RawASP) for elements in self._segments.values() for element in elements)
        if has_raw:
            return
        # Derivation evidence comes from the program's own rules: a show_when
        # condition's atoms must not vouch for themselves
        segment_signs = {
            (cls, negated)
            for elements in self._segments.values()
            for element in elements
            for cls, negated, is_atom in element.collect_predicate_signs()
            if is_atom
        }
        atom_classes = {cls for cls, _negated in segment_signs}
        for pred, visibility in self._show_overrides.items():
            if visibility is True and pred not in atom_classes:
                raise ValueError(
                    f"show({pred.__name__}) was called, but no {pred.get_name()}/{pred.get_arity()} "
                    f"atoms occur anywhere in the program — nothing derives it. (If it were "
                    f"emitted, gringo would reject the dangling #show directive.)"
                )
        for pred, negated in self._show_when_overrides:
            if (pred, negated) not in segment_signs:
                sign = "-" if negated else ""
                raise ValueError(
                    f"show_when was registered for {sign}{pred.get_name()}/{pred.get_arity()}, "
                    f"but no such atoms occur anywhere in the program — nothing derives them."
                )

    def _optimizes(self) -> bool:
        """
        Whether this program optimizes: a native minimize()/maximize()
        directive, or a raw block containing #minimize/#maximize/:~ (the
        scanner ignores comments and strings; the solve-time cost check
        backstops anything it cannot see).
        """
        for elements in self._segments.values():
            for element in elements:
                if isinstance(element, OptimizationDirective):
                    return True
                if isinstance(element, RawASP) and raw_text_optimizes(element.text):
                    return True
        return False

    def _validate_names(self) -> None:
        """
        Raise on naming collisions that would corrupt solving:

        - two distinct predicate classes sharing (name, arity): solutions could not
          be reconstructed unambiguously
        - a nullary predicate sharing its name with a #const: gringo substitutes
          the constant's value into the atom, silently corrupting round-trips
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

        # 3. Program segments
        first_segment = True
        for segment_name, elements in self._segments.items():
            if len(self._segments) > 1 and len(elements) > 0:
                # Don't put double newlines for the first segment
                if not first_segment:
                    lines.append("")
                else:
                    first_segment = False
                lines.extend(("", f"% ===== {segment_name.replace('_', ' ').title()} ====="))
            lines.extend(element.render() for element in elements)

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
        signs = self._collect_predicate_signs()
        walked_positive = {cls for cls, negated, is_atom in signs if is_atom and not negated}
        has_raw = any(isinstance(element, RawASP) for elements in self._segments.values() for element in elements)
        override_positive = {
            cls
            for cls, visibility in self._show_overrides.items()
            if visibility is True and (cls in walked_positive or has_raw)
        }
        positive_classes = walked_positive | override_positive
        negated_classes = {cls for cls, negated, is_atom in signs if is_atom and negated}
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

        for _segment_name, elements in self._segments.items():
            for element in elements:
                constants.update(element.collect_defined_constants())

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

        optimizes = self._optimizes()
        if self.project_shown and optimizes:
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
        # every model's full atom set is checked against declared signatures
        # (the raw_asp contract: exhaustive declaration)
        has_raw = any(isinstance(element, RawASP) for elements in self._segments.values() for element in elements)

        return GroundedProgram(
            asp_source,
            control,
            predicate_types,
            message_handler,
            check_all_atoms=has_raw,
            defined_constants=dict(self._defined_constants),
            optimizes=optimizes,
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
                     been yielded and 'exhausted' remains False.
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
    the atoms true in every/some answer set (with refine() as their
    step-by-step primitive), and assumptions parameterize any of them per
    call.

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
        check_all_atoms: bool,
        defined_constants: dict[str, int | str] | None = None,
        optimizes: bool = False,
    ) -> None:
        self._text = text
        self._control = control
        self._predicate_types = predicate_types
        self._message_handler = message_handler
        self._check_all_atoms = check_all_atoms
        self._defined_constants = defined_constants or {}
        self._optimizes = optimizes
        self._active: SearchABC | None = None

    @property
    def text(self) -> str:
        """The rendered ASP program this grounding solves."""
        return self._text

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
        mode: RefinementMode | None,
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
        if timeout < 0:
            raise ValueError(f"timeout must be non-negative, got {timeout}")
        if self._optimizes:
            if mode is None:
                raise ValueError("This program optimizes (#minimize/#maximize present). Solve it with optimize().")
            raise ValueError(
                f"{mode.value} consequences over an optimizing program are computed "
                f"against the solver's cost-descent path, not the set of optimal "
                f"models — the result would be wrong. Remove the optimization "
                f"directive to ask about all answer sets."
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
        solve_config.enum_mode = mode.value if mode is not None else "auto"
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
            check_all_atoms=self._check_all_atoms,
            assumptions=converted,
        )
        return result

    def refine(
        self,
        mode: RefinementMode,
        timeout: float = 0,
        assumptions: Sequence[Predicate | DefaultNegation] | None = None,
    ) -> RefinementSteps:
        """
        Step through a consequence refinement yourself: iterate for
        successive approximations (claim-free AtomCollections) — CAUTIOUS
        shrinking toward the intersection, BRAVE growing toward the union —
        and stop whenever your question is answered, e.g. the atom you care
        about has dropped out of a cautious approximation (certified
        not-forced) or arrived in a brave one (certified possible). Each
        step is a full solver search, so control between steps is control
        over real work. See RefinementSteps for the full contract;
        cautious()/brave() are the eager forms.
        """
        converted = self._begin_solve(mode, timeout, assumptions)
        self._active = steps = RefinementSteps(
            self._control,
            self._predicate_types,
            timeout,
            self._message_handler,
            converted or [],
            mode,
            check_all_atoms=self._check_all_atoms,
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
        are forced" is this question. Eager sugar over refine(CAUTIOUS).
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
        are possible" is this question. Eager sugar over refine(BRAVE).
        Returns None if the program is unsatisfiable.

        timeout (seconds) and max_iterations (refinement steps) each bound
        the work, 0 meaning unbounded; a bounded run returns an INCOMPLETE
        result (complete=False) whose every atom is still certified
        possible — see BraveConsequences. Raises ValueError if the program
        optimizes (see cautious()).
        """
        return self._refine_eagerly(RefinementMode.BRAVE, BraveConsequences, timeout, max_iterations, assumptions)

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
        steps = self.refine(mode, timeout, assumptions)
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
