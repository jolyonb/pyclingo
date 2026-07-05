import time
from collections import defaultdict
from collections.abc import Generator, Sequence
from datetime import datetime
from typing import Any

import clingo

from pyclingo.choice import Choice
from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel
from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.core import ConstantBase, DefinedConstant, Number, String, Term
from pyclingo.predicate import Predicate
from pyclingo.program_elements import BlankLine, Comment, ProgramElement, RawASP, Rule
from pyclingo.statistics import format_statistics_clingo_style


class ASPProgram:
    """
    Represents a complete ASP program.

    This class manages a collection of rules, comments, and other elements
    that make up an ASP program, and provides methods to build and render
    the program.
    """

    header: str | None = None
    default_segment: str = "Rules"

    satisfiable: bool | None = None
    exhausted: bool | None = None
    solution_count: int | None = None
    _clingo_statistics: dict[str, Any] | None = None

    def __init__(self, header: str | None = None, default_segment: str = "Rules") -> None:
        """Initialize an empty ASP program."""
        self._segments: defaultdict[str, list[ProgramElement]] = defaultdict(list)
        self._defined_constants: dict[str, int | str] = {}
        self._show_overrides: dict[type[Predicate], bool | ConditionalLiteral] = {}
        self._solving = False
        self.header = header
        self.default_segment = default_segment.lower()

    def add_segment(self, segment: str) -> None:
        """
        Pre-declare an empty segment, fixing its position in the rendered output.

        Declaration is optional: writing to a new segment name (fact/when/forbid/
        comment) creates it on first use, ordered by first write. Declaring an
        already-existing segment is an error, because its position is already set
        and the request can't be honored.
        """
        # Normalize segment name to lowercase for case-insensitive handling
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

    def when(self, conditions: Term | Sequence[Term], let: Term, segment: str | None = None) -> None:
        """Create a clingo rule which sets the let term when all conditions are satisfied."""
        if isinstance(conditions, str):
            raise TypeError("when() conditions must be Terms, not a string")
        condition_list = list(conditions) if isinstance(conditions, Sequence) else [conditions]
        if not condition_list:
            raise ValueError("when() requires at least one condition; use fact() for unconditional statements")
        for condition in condition_list:
            if not isinstance(condition, Term):
                raise TypeError(f"when() conditions must be Terms, got {type(condition).__name__}")
        if not isinstance(let, Term):
            raise TypeError(f"when() let must be a Term, got {type(let).__name__}")
        segment_key = (segment or self.default_segment).lower()
        self._segments[segment_key].append(Rule(head=let, body=condition_list))

    def forbid(self, *conditions: Term, segment: str | None = None) -> None:
        """Creates a clingo constraint which forbids the specified combination of conditions."""
        if not conditions:
            raise ValueError("forbid() requires at least one condition")
        for condition in conditions:
            if not isinstance(condition, Term):
                raise TypeError(f"forbid() conditions must be Terms, got {type(condition).__name__}")
        segment_key = (segment or self.default_segment).lower()
        self._segments[segment_key].append(Rule(body=list(conditions)))

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

        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Constant name can only contain letters, digits, and underscores: {name}")

        if name in self._defined_constants:
            raise ValueError(f"Defined constant '{name}' is already registered")

        if not isinstance(value, (int, str)):
            raise TypeError(f"Constant value must be an integer or string, got {type(value).__name__}")

        self._defined_constants[name] = value

        return DefinedConstant(name)

    def show(self, predicate: type[Predicate]) -> None:
        """Show this predicate in output, overriding its default visibility."""
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

    def _validate_names(self) -> None:
        """
        Raise on naming collisions that would corrupt solving:

        - two distinct predicate classes sharing (name, arity): solutions could not
          be reconstructed unambiguously
        """
        by_signature: dict[tuple[str, int], type[Predicate]] = {}
        for pred in self._collect_predicates():
            key = (pred.get_name(), pred.get_arity())
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

        # 1. Header comments
        lines: list[str] = []
        if self.header:
            lines.append(f"% {self.header}")
        lines.append(f"% Generated by pyclingo on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 2. #const definitions (only those actually used are emitted)
        used_defined_constants = self._collect_used_defined_constants()
        if self._defined_constants:
            for name, value in self._defined_constants.items():
                if name not in used_defined_constants:
                    continue
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
        for pred in self._collect_predicates():
            visibility = self._show_overrides.get(pred, pred.shown_by_default())
            if visibility is True:
                show_statements.add(f"#show {pred.get_name()}/{pred.get_arity()}.")
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

    def solve(
        self, models: int = 1000, timeout: int = 0, stop_on_log_level: LogLevel = LogLevel.INFO
    ) -> Generator[dict[str, list[Predicate]]]:
        """
        Solve the ASP program and yield solutions as sets of Predicate objects.

        Args:
            models: Maximum number of models to compute. Pass 0 to enumerate all models —
                    beware that an underconstrained program may make this effectively endless.
            timeout: Wall-clock limit in seconds (0 for no limit). On timeout, models found
                     so far will have been yielded and 'exhausted' remains False.
            stop_on_log_level: Log level at which to abort solving

        Yields:
            For each solution, a dictionary mapping predicate names to lists of Predicate instances

        Raises:
            RuntimeError: If a solve is already in progress on this program, if an error
                occurs during parsing or grounding, or if the log level threshold is exceeded

        Notes:
            Rendering, grounding, and their error checks run eagerly at this call; only
            model enumeration is lazy. One solve runs at a time per program: this call
            claims the program, and exhausting or closing the returned generator releases
            it. To stop early, call .close() on the generator; 'satisfiable', 'exhausted',
            'solution_count', and the solver statistics are finalized on every exit path.
        """
        if self._solving:
            raise RuntimeError(
                "A solve is already in progress on this program: "
                "exhaust or close() the existing solve() generator first"
            )
        if timeout < 0:
            raise ValueError(f"timeout must be non-negative, got {timeout}")

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

        # Map (name, arity) to predicate class for solution reconstruction: arity
        # matters because p/1 and p/2 are distinct predicates in ASP
        predicate_types = {(pred.get_name(), pred.get_arity()): pred for pred in self._collect_predicates()}

        # Claim the program and reset solve state before handing over to the lazy iterator
        self._solving = True
        self.satisfiable = None
        self.exhausted = False
        self.solution_count = 0
        deadline = time.monotonic() + timeout if timeout > 0 else None

        generator = self._solve_iterator(control, predicate_types, deadline, tic)
        # Prime past the sentinel yield so the iterator's cleanup is armed even if the
        # caller closes or abandons the generator without ever iterating it
        next(generator)
        return generator

    def _solve_iterator(
        self,
        control: clingo.Control,
        predicate_types: dict[tuple[str, int], type[Predicate]],
        deadline: float | None,
        tic: float,
    ) -> Generator[dict[str, list[Predicate]]]:
        """
        Lazy half of solve(): yields models and finalizes bookkeeping on every exit path
        (exhaustion, close(), exception, or garbage collection of the generator).
        """
        result: clingo.SolveResult | None = None
        solution_count = 0
        try:
            # Sentinel consumed by solve()'s priming next(); callers never see it
            yield {}

            # Wall-clock timeouts require async solving: clingo has no timeout
            # configuration key; instead we wait on the handle and cancel at the deadline.
            with control.solve(yield_=True, async_=True) as handle:
                try:
                    while True:
                        handle.resume()
                        # Clamp to zero: wait() treats a negative timeout as "block forever",
                        # but a passed deadline should poll and cancel instead
                        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                        if not handle.wait(remaining):
                            # The deadline passed before the next model was found
                            break
                        model = handle.model()
                        if model is None:
                            break
                        solution_count += 1
                        self.solution_count = solution_count
                        self.satisfiable = True
                        yield self._convert_model_to_predicates(model, predicate_types)
                finally:
                    # Also reached when the caller close()s mid-iteration. Cancelling a
                    # finished search is a no-op, so this is safe on every path.
                    handle.cancel()
                    # After a cancelled solve, satisfiability may be unknown (None);
                    # keep what we learned from any yielded models.
                    final: clingo.SolveResult = handle.get()
                    if final.satisfiable is not None:
                        self.satisfiable = final.satisfiable
                    self.exhausted = final.exhausted
                    result = final
        finally:
            self._solving = False
            if result is not None:
                # Store the raw clingo statistics for detailed formatting. Skipped if the
                # generator was closed before solving began (statistics would be empty).
                self._clingo_statistics = dict(control.statistics)
                self._clingo_statistics["total_time"] = time.perf_counter() - tic

    def _convert_symbol_to_predicate(
        self, symbol: clingo.Symbol, predicate_types: dict[tuple[str, int], type[Predicate]]
    ) -> Predicate:
        """
        Convert a clingo model symbol back into a typed Predicate instance, recursively.

        Raises:
            ValueError: If the symbol's name/arity doesn't match any known predicate.
        """
        pred_name = symbol.name
        key = (pred_name, len(symbol.arguments))

        if key not in predicate_types:
            raise ValueError(f"Unknown predicate type: {pred_name}/{len(symbol.arguments)}")

        pred_class = predicate_types[key]
        field_names = [f.name for f in pred_class.argument_fields()]

        kwargs: dict[str, ConstantBase | Predicate] = {}
        for i, (arg, field_name) in enumerate(zip(symbol.arguments, field_names, strict=True)):
            if arg.type == clingo.SymbolType.Number:
                kwargs[field_name] = Number(arg.number)
            elif arg.type == clingo.SymbolType.String:
                kwargs[field_name] = String(arg.string)
            elif arg.type == clingo.SymbolType.Function:
                # Recursively convert nested predicates; bare atoms are nullary predicates
                kwargs[field_name] = self._convert_symbol_to_predicate(arg, predicate_types)
            else:
                raise ValueError(f"Unsupported symbol type in argument {i} of {pred_name}: {arg.type}")

        return pred_class(**kwargs)

    def _convert_model_to_predicates(
        self, model: clingo.Model, predicate_types: dict[tuple[str, int], type[Predicate]]
    ) -> dict[str, list[Predicate]]:
        """Convert a clingo model into {predicate_name: [Predicate instances]}."""
        result = defaultdict(list)

        for symbol in model.symbols(shown=True):
            pred_instance = self._convert_symbol_to_predicate(symbol, predicate_types)
            result[pred_instance.get_name()].append(pred_instance)

        return dict(result)

    def format_statistics_clingo_style(self) -> str:
        """Format the last solve's statistics in clingo's native style."""
        if self._clingo_statistics is None:
            return "No statistics available"
        return format_statistics_clingo_style(self._clingo_statistics)
