import time
from collections import defaultdict
from collections.abc import Sequence

import clingo

from pyclingo.choice import Choice
from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel
from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.core import AtomSign, Comparison, DefinedConstant, Pool, Term
from pyclingo.predicate import Predicate
from pyclingo.program_elements import BlankLine, Comment, ProgramElement, RawASP, Rule
from pyclingo.scoping import validate_rule
from pyclingo.solve_result import SolveResult
from pyclingo.version import __version__


class ASPProgram:
    """
    Represents a complete ASP program.

    This class manages a collection of rules, comments, and other elements
    that make up an ASP program, and provides methods to build and render
    the program.
    """

    def __init__(self, header: str | None = None, default_segment: str = "Rules") -> None:
        """Initialize an empty ASP program."""
        if header is not None and ("\n" in header or "\r" in header):
            raise ValueError("Program header must be a single line (it renders as one % comment)")
        self._segments: defaultdict[str, list[ProgramElement]] = defaultdict(list)
        self._defined_constants: dict[str, int | str] = {}
        self._show_overrides: dict[type[Predicate], bool | ConditionalLiteral] = {}
        self.header: str | None = header
        self.default_segment: str = default_segment.lower()

    def add_segment(self, segment: str) -> None:
        """
        Pre-declare an empty segment, fixing its position in the rendered output.

        Declaration is optional: writing to a new segment name (fact/when/forbid/
        comment) creates it on first use, ordered by first write. Declaring an
        already-existing segment is an error, because its position is already set
        and the request can't be honored.
        """
        # Normalize segment name to lowercase for case-insensitive handling
        if "\n" in segment or "\r" in segment:
            raise ValueError("Segment names must be single-line (they render as section comments)")
        normalized_segment = segment.lower()
        if normalized_segment in self._segments:
            raise ValueError(f"Segment '{segment}' already exists")
        self._segments[normalized_segment] = []

    def fact(self, *facts: Predicate | Choice, segment: str | None = None) -> None:
        """
        Add unconditional statements to the program: grounded facts, or bare
        choice rules like { a(1..3) } (whose element variables are local).
        """
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
            segment_key = (segment or self.default_segment).lower()
            self._segments[segment_key].append(Rule(head=statement))

    def when(self, *conditions: Term, let: Term, segment: str | None = None) -> None:
        """Create a clingo rule which sets the let term when all conditions are satisfied."""
        if not conditions:
            raise ValueError("when() requires at least one condition; use fact() for unconditional statements")
        for condition in conditions:
            if not isinstance(condition, Term):
                raise TypeError(f"when() conditions must be Terms, got {type(condition).__name__}")
        if not isinstance(let, Term):
            raise TypeError(f"when() let must be a Term, got {type(let).__name__}")
        segment_key = (segment or self.default_segment).lower()
        self._segments[segment_key].append(Rule(head=let, body=list(conditions)))

    def forbid(self, *conditions: Term, segment: str | None = None) -> None:
        """Creates a clingo constraint which forbids the specified combination of conditions."""
        if not conditions:
            raise ValueError("forbid() requires at least one condition")
        for condition in conditions:
            if not isinstance(condition, Term):
                raise TypeError(f"forbid() conditions must be Terms, got {type(condition).__name__}")
        segment_key = (segment or self.default_segment).lower()
        self._segments[segment_key].append(Rule(body=list(conditions)))

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

    def raw_asp(self, text: str, segment: str | None = None, predicates: Sequence[type[Predicate]] = ()) -> None:
        """
        Add a verbatim block of ASP text: the escape hatch for constructs
        pyclingo does not model.

        Declare any predicates the block produces via predicates so that show
        directives cover them and solutions round-trip into typed instances.
        """
        if not isinstance(text, str):
            raise TypeError(f"raw_asp() text must be a string, got {type(text).__name__}")
        segment_key = (segment or self.default_segment).lower()
        self._segments[segment_key].append(RawASP(text, predicates))

    def comment(self, text: str, segment: str | None = None) -> None:
        """Add a comment to the program."""
        segment_key = (segment or self.default_segment).lower()
        self._segments[segment_key].append(Comment(text))

    def blank_line(self, segment: str | None = None) -> None:
        """Add a blank line to the program for formatting."""
        segment_key = (segment or self.default_segment).lower()
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
        if not name or not name[0].islower():
            raise ValueError(f"Constant name must start with a lowercase letter: {name}")
        if name == "not":
            raise ValueError("'not' is reserved in ASP and cannot be a constant name")

        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Constant name can only contain letters, digits, and underscores: {name}")

        if name in self._defined_constants:
            raise ValueError(f"Defined constant '{name}' is already registered")

        if not isinstance(value, (int, str)):
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

    def show_when(self, predicate: type[Predicate], condition: ConditionalLiteral) -> None:
        """
        Show this predicate only where the condition holds, e.g.
        show_when(P, ConditionalLiteral(p(C), [p(C), ~outside(C)])) renders as
        "#show p(C) : p(C), not outside(C)."
        """
        if not isinstance(condition, ConditionalLiteral):
            raise TypeError(f"show_when condition must be a ConditionalLiteral, got {type(condition).__name__}")
        # A show directive is a capture too: freeze so later mutation of a
        # shared builder cannot silently rewrite it, and validate its variables
        # (a #show directive has no rule body, so everything must be bound
        # inside the conditional literal itself)
        validate_rule(None, [condition], f"#show {condition.render()}.")
        condition.freeze()
        self._show_overrides[predicate] = condition

    def _collect_predicates(self) -> set[type[Predicate]]:
        """Collect all predicate classes used anywhere in the program, show_when conditions included."""
        predicates = set()

        for _segment_name, elements in self._segments.items():
            for element in elements:
                predicates.update(element.collect_predicates())

        for visibility in self._show_overrides.values():
            if isinstance(visibility, ConditionalLiteral):
                predicates.update(visibility.collect_predicates())

        return predicates

    def _collect_predicate_signs(self) -> set[AtomSign]:
        """(class, negated, is_atom) occurrences across the whole program."""
        signs: set[AtomSign] = set()
        for elements in self._segments.values():
            for element in elements:
                signs.update(element.collect_predicate_signs())
        for visibility in self._show_overrides.values():
            if isinstance(visibility, ConditionalLiteral):
                signs.update(visibility.collect_predicate_signs())
        return signs

    def _validate_shown_predicates(self) -> None:
        """
        Raise for show() of a predicate with no atom occurrences — but only
        when the program has no raw_asp blocks: raw text is invisible to the
        walkers, so with raw blocks present an uncollected predicate may
        still be derived (that is what raw_asp's predicates= is for).
        """
        has_raw = any(isinstance(element, RawASP) for elements in self._segments.values() for element in elements)
        if has_raw:
            return
        atom_classes = {cls for cls, _negated, is_atom in self._collect_predicate_signs() if is_atom}
        for pred, visibility in self._show_overrides.items():
            if visibility is True and pred not in atom_classes:
                raise ValueError(
                    f"show({pred.__name__}) was called, but no {pred.get_name()}/{pred.get_arity()} "
                    f"atoms occur anywhere in the program — nothing derives it. (If it were "
                    f"emitted, gringo would reject the dangling #show directive.)"
                )

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
                lines.extend(("", f"% ===== {segment_name.title()} ====="))
            lines.extend(element.render() for element in elements)

        # 4. #show directives: program overrides first, class defaults second.
        # The bare "#show." must be emitted whenever ANY predicate is hidden, even if
        # nothing is shown — without it, clingo defaults to showing every atom.
        show_statements: set[str] = set()
        any_hidden = False
        # Each sign has its own show signature, and a directive for an absent
        # signature draws a gringo info — so emit per present sign. An
        # explicit show() override counts as positive presence (the user
        # asked; raw_asp-only predicates have no walkable occurrences).
        signs = self._collect_predicate_signs()
        positive_classes = {cls for cls, negated, is_atom in signs if is_atom and not negated} | set(
            self._show_overrides
        )
        negated_classes = {cls for cls, negated, is_atom in signs if is_atom and negated}
        for pred in self._collect_predicates() | set(self._show_overrides):
            visibility = self._show_overrides.get(pred, pred.shown_by_default())
            if visibility is True:
                if pred in positive_classes:
                    show_statements.add(f"#show {pred.get_name()}/{pred.get_arity()}.")
                if pred in negated_classes:
                    show_statements.add(f"#show -{pred.get_name()}/{pred.get_arity()}.")
            elif isinstance(visibility, ConditionalLiteral):
                show_statements.add(f"#show {visibility.render()}.")
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

        for visibility in self._show_overrides.values():
            if isinstance(visibility, ConditionalLiteral):
                constants.update(visibility.collect_defined_constants())

        return constants

    def _validate_constants(self) -> None:
        """Raise if any constant used in the program was never declared via define_constant()."""
        used_constants = self._collect_used_defined_constants()

        if unregistered := used_constants - set(self._defined_constants.keys()):
            raise ValueError(f"Undefined constants used in program: {', '.join(sorted(unregistered))}")

    def solve(self, models: int = 1, timeout: float = 0, stop_on_log_level: LogLevel = LogLevel.INFO) -> SolveResult:
        """
        Solve the ASP program, returning a SolveResult that yields Models lazily.

        Args:
            models: Maximum number of models to compute; defaults to 1, matching
                    clingo's own default — enumeration is an explicit ask. Pass 0 to
                    enumerate all models; beware that an underconstrained program may
                    make this effectively endless.
            timeout: Wall-clock limit in seconds (0 for no limit), counted from the
                     start of iteration. On timeout, models found so far will have
                     been yielded and 'exhausted' remains False.
            stop_on_log_level: Log level at which to abort solving

        Returns:
            A SolveResult: iterate it for Models (each with typed atoms() access);
            its satisfiable/exhausted/solution_count/statistics finalize when
            iteration ends on any path (exhaustion, close(), or a with-block).

        Raises:
            RuntimeError: If an error occurs during parsing or grounding, or the
                log level threshold is exceeded

        Notes:
            Rendering, grounding, and their error checks run eagerly at this call; only
            model enumeration is lazy. Every call returns an independent SolveResult,
            so repeated solves on one program never interfere.
        """
        if timeout < 0:
            raise ValueError(f"timeout must be non-negative, got {timeout}")
        if models < 0:
            raise ValueError(f"models must be non-negative (0 enumerates all), got {models}")

        tic = time.perf_counter()

        # Render the ASP program first
        asp_source = self.render()

        # Create message handler with the ASP source and specified stop level
        message_handler = ClingoMessageHandler(asp_source, stop_on_level=stop_on_log_level)

        # Configure and prepare the control object
        control = clingo.Control(logger=message_handler.on_message, arguments=["--stats"])
        assert isinstance(control.configuration.solve, clingo.Configuration)
        control.configuration.solve.models = models

        # Add and ground the program
        try:
            control.add("base", [], asp_source)
        except RuntimeError as e:
            # Handle parsing errors
            error_msg = str(e)
            if formatted_messages := message_handler.format_all_messages(verb="parsing"):
                error_msg += "\n\n" + formatted_messages
            raise RuntimeError(error_msg) from e

        try:
            control.ground([("base", [])])
        except RuntimeError as e:
            # Handle grounding errors
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

        predicate_types = {(pred.get_name(), pred.get_arity()): pred for pred in self._collect_predicates()}

        return SolveResult(control, predicate_types, timeout, tic)
