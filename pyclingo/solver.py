from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Generator, Sequence

import clingo

from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel
from pyclingo.predicate import Predicate
from pyclingo.program_elements import BlankLine, Comment, ProgramElement, Rule
from pyclingo.term import Term
from pyclingo.value import Constant, ConstantBase, StringConstant, SymbolicConstant


class ASPProgram:
    """
    Represents a complete ASP program.

    This class manages a collection of rules, comments, and other elements
    that make up an ASP program, and provides methods to build and render
    the program.
    """

    header: str | None = None
    default_segment: str = "Rules"

    solved: bool = False
    satisfiable: bool | None = None
    exhausted: bool | None = None
    solution_count: int | None = None
    _clingo_statistics: dict[str, Any] | None = None

    def __init__(self, header: str | None = None, default_segment: str = "Rules") -> None:
        """Initialize an empty ASP program."""
        self._segments: defaultdict[str, list[ProgramElement]] = defaultdict(list)
        self._symbolic_constants: dict[str, int | str] = {}
        self.header = header
        self.default_segment = default_segment

    def add_segment(self, segment: str) -> None:
        """Add a new segment to the program."""
        if segment in self._segments:
            raise ValueError(f"Segment '{segment}' already exists")
        self._segments[segment] = []

    def fact(self, *predicates: Predicate, segment: str | None = None) -> None:
        """Add one or more unconditional facts to the program."""
        assert all(isinstance(predicate, Predicate) for predicate in predicates)
        for predicate in predicates:
            self._segments[segment or self.default_segment].append(Rule(head=predicate))

    def when(self, conditions: Term | Sequence[Term], let: Term, segment: str | None = None) -> None:
        """Create a clingo rule which sets the let term when all conditions are satisfied."""
        condition_list = list(conditions) if isinstance(conditions, Sequence) else [conditions]
        assert all(isinstance(condition, Term) for condition in condition_list)
        assert isinstance(let, Term)
        self._segments[segment or self.default_segment].append(Rule(head=let, body=condition_list))

    def forbid(self, *conditions: Term, segment: str | None = None) -> None:
        """Creates a clingo constraint which forbids the specified combination of conditions."""
        assert all(isinstance(condition, Term) for condition in conditions)
        self._segments[segment or self.default_segment].append(Rule(body=list(conditions)))

    def comment(self, text: str, segment: str | None = None) -> None:
        """
        Add a comment to the program.

        Args:
            text: The comment text.
            segment: The segment to add this comment to
        """
        self._segments[segment or self.default_segment].append(Comment(text))

    def blank_line(self, segment: str | None = None) -> None:
        """Add a blank line to the program for formatting."""
        self._segments[segment or self.default_segment].append(BlankLine())

    def section(self, title: str, segment: str | None = None) -> None:
        """
        Add a section header to the program.

        Args:
            title: The section title.
            segment: The segment to add this section to
        """
        self.blank_line(segment=segment)
        self.comment(title, segment=segment)

    def register_symbolic_constant(self, name: str, value: int | str) -> SymbolicConstant:
        """
        Register a symbolic constant with the program.

        Args:
            name: The name of the constant.
            value: The value of the constant (integer or string).

        Raises:
            ValueError: If the name is invalid or already registered.
            TypeError: If the value is not an integer or string.
        """
        # Validate name
        assert isinstance(name, str)
        if not name or not name[0].islower():
            raise ValueError(f"Constant name must start with a lowercase letter: {name}")

        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Constant name can only contain letters, digits, and underscores: {name}")

        # Check for duplicate registration
        if name in self._symbolic_constants:
            raise ValueError(f"Symbolic constant '{name}' is already registered")

        # Validate value type
        if not isinstance(value, (int, str)):
            raise TypeError(f"Constant value must be an integer or string, got {type(value).__name__}")

        # Store the constant
        self._symbolic_constants[name] = value

        return SymbolicConstant(name)

    def _collect_predicates(self) -> set[type[Predicate]]:
        """
        Collect all predicates used in the program.

        Returns:
            set[Predicate]: Set of all predicates used in the program.
        """
        predicates = set()

        for segment_name, elements in self._segments.items():
            for element in elements:
                predicates.update(element.collect_predicates())

        return predicates

    def render(self) -> str:
        """
        Render the complete ASP program.

        Generates the program text including:
        1. Constant definitions
        2. Program elements (rules, comments, etc.)
        3. Show directives

        Returns:
            str: The complete ASP program.
        """
        # Perform validation
        self._validate_constants()

        # Generate a header
        lines: list[str] = []
        if self.header:
            lines.append(f"% {self.header}")
        lines.append(f"% Generated by pyclingo on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 2. Add constant definitions
        used_symbolic_constants = self._collect_used_symbolic_constants()
        if self._symbolic_constants:
            for name, value in self._symbolic_constants.items():
                if name not in used_symbolic_constants:
                    # Only output constants used in the program
                    continue
                if isinstance(value, str):
                    lines.append(f'#const {name} = "{value}".')  # String values are quoted
                else:
                    lines.append(f"#const {name} = {value}.")  # Integer values are not

        # 3. Add program elements for each segment
        first_segment = True
        for segment_name, elements in self._segments.items():
            if len(self._segments) > 1 and len(elements) > 0:
                # Don't put double newlines for the first segment
                if not first_segment:
                    lines.extend("")
                else:
                    first_segment = False
                lines.extend(("", f"% ===== {segment_name.title()} ====="))
            lines.extend(element.render() for element in elements)

        show_statements: set[str]
        if show_statements := {
            pred.get_show_directive()  # type: ignore[misc]
            for pred in self._collect_predicates()
            if pred.get_show_directive() is not None
        }:
            lines.extend(("", "#show."))
            lines.extend(sorted(list(show_statements)))

        # 5. Join everything together
        return "\n".join(lines) + "\n"

    def _collect_used_symbolic_constants(self) -> set[str]:
        """
        Collect all symbolic constant names used in the program.

        Returns:
            set[str]: Set of symbolic constant names used in the program.
        """
        constants = set()

        for segment_name, elements in self._segments.items():
            for element in elements:
                constants.update(element.collect_symbolic_constants())

        return constants

    def _validate_constants(self) -> None:
        """
        Validate that all symbolic constants used in the program are registered.

        Raises:
            ValueError: If unregistered constants are found.
        """
        used_constants = self._collect_used_symbolic_constants()

        if unregistered := used_constants - set(self._symbolic_constants.keys()):
            raise ValueError(f"Unregistered symbolic constants used in program: {', '.join(sorted(unregistered))}")

    def solve(
        self, models: int = 0, timeout: int = 0, stop_on_log_level: LogLevel = LogLevel.INFO
    ) -> Generator[dict[str, list[Predicate]], None, None]:
        """
        Solve the ASP program and yield solutions as sets of Predicate objects.

        Args:
            models: Maximum number of models to compute (0 for all)
            timeout: Timeout in seconds (0 for no timeout)
            stop_on_log_level: Log level at which to abort solving

        Yields:
            For each solution, a dictionary mapping Predicate types to lists of Predicate instances

        Raises:
            RuntimeError: If an error occurs during solving or grounding, or if log level threshold is exceeded

        Notes:
            After all models are yielded, solver statistics are stored in the
            'statistics' attribute of the ASPProgram instance.
        """
        tic = time.perf_counter()

        # Render the ASP program first
        asp_source = self.render()

        # Create message handler with the ASP source and specified stop level
        message_handler = ClingoMessageHandler(asp_source, stop_on_level=stop_on_log_level)

        # Configure and prepare the control object
        control = clingo.Control(logger=message_handler.on_message, arguments=["--stats"])
        assert isinstance(control.configuration.solve, clingo.Configuration)
        control.configuration.solve.models = models or 1000  # Maximum of 1000 rather than unlimited
        if timeout > 0:
            control.configuration.solve.timeout = timeout

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

        # Check for messages after grounding
        if message_handler.messages:
            print(message_handler.format_all_messages(verb="grounding"))

            # Check if we should halt based on log level
            if message_handler.should_halt:
                assert message_handler.highest_level is not None
                raise RuntimeError(
                    f"Grounding produced {message_handler.highest_level.name} level messages "
                    f"(stop threshold: {stop_on_log_level.name})."
                )

        # Get a mapping of predicate names to their types for reconstruction
        predicate_types = {pred.get_name(): pred for pred in self._collect_predicates()}

        # Continue with solving
        self.exhausted = False
        self.solution_count = 0
        with control.solve(yield_=True) as handle:
            for model in handle:
                self.solution_count += 1
                self.satisfiable = True
                yield self._convert_model_to_predicates(model, predicate_types)

            # Save final solve result information
            result = handle.get()
            self.satisfiable = result.satisfiable
            self.exhausted = result.exhausted

        toc = time.perf_counter()

        # Store the raw clingo statistics for detailed formatting
        self._clingo_statistics = dict(control.statistics)
        self._clingo_statistics["total_time"] = toc - tic

    def _convert_symbol_to_predicate(
        self, symbol: clingo.Symbol, predicate_types: dict[str, type[Predicate]]
    ) -> Predicate:
        """
        Convert a clingo symbol to a Predicate object.

        Args:
            symbol: A clingo Symbol object representing an atom
            predicate_types: Dictionary mapping predicate names to Predicate classes

        Returns:
            A Predicate instance corresponding to the symbol

        Raises:
            ValueError: If the symbol cannot be converted to a predicate
        """
        # Get predicate name
        pred_name = symbol.name

        if pred_name not in predicate_types:
            raise ValueError(f"Unknown predicate type: {pred_name}")

        pred_class = predicate_types[pred_name]
        field_names = [f.name for f in pred_class.argument_fields()]

        # Verify argument count
        if len(symbol.arguments) != len(field_names):
            raise ValueError(
                f"Arity mismatch for predicate {pred_name}: "
                f"got {len(symbol.arguments)} arguments, expected {len(field_names)}"
            )

        # Convert arguments to appropriate Value objects
        kwargs: dict[str, ConstantBase | Predicate] = {}
        for i, (arg, field_name) in enumerate(zip(symbol.arguments, field_names)):
            # Convert argument based on its type
            if arg.type == clingo.SymbolType.Number:
                kwargs[field_name] = Constant(arg.number)
            elif arg.type == clingo.SymbolType.String:
                kwargs[field_name] = StringConstant(arg.string)
            elif arg.type == clingo.SymbolType.Function:
                # Recursively convert nested predicates
                nested_pred = self._convert_symbol_to_predicate(arg, predicate_types)
                kwargs[field_name] = nested_pred
            else:
                raise ValueError(f"Unsupported symbol type in argument {i} of {pred_name}: {arg.type}")

        # Create and return the predicate instance
        return pred_class(**kwargs)

    def _convert_model_to_predicates(
        self, model: clingo.Model, predicate_types: dict[str, type[Predicate]]
    ) -> dict[str, list[Predicate]]:
        """
        Convert a clingo model to a dictionary of Predicate objects.

        Args:
            model: A clingo model containing symbols
            predicate_types: Dictionary mapping predicate names to Predicate classes

        Returns:
            Dictionary mapping Predicate types to lists of Predicate instances
        """
        result = defaultdict(list)

        for symbol in model.symbols(shown=True):
            pred_instance = self._convert_symbol_to_predicate(symbol, predicate_types)
            result[pred_instance.get_name()].append(pred_instance)

        return dict(result)

    def format_statistics_clingo_style(self) -> str:
        """
        Format statistics in the same style as clingo's native output.

        Most of these statistics are output in https://github.com/potassco/clasp/blob/master/clasp/solver_types.h
        if you want to see the original calculations!

        Returns:
            str: Formatted statistics string matching clingo's output format
        """
        if self._clingo_statistics is None:
            return "No statistics available"

        stats = self._clingo_statistics  # Raw clingo statistics

        # Models and Calls
        models_enumerated = int(stats["summary"]["models"]["enumerated"])
        calls = int(stats["summary"]["call"]) + 1  # clingo seems to add 1
        lines = [
            f"Models       : {models_enumerated}",
            f"Calls        : {calls}",
        ]

        # Time information
        total_time = stats["total_time"]
        solving_time = stats["summary"]["times"]["solve"]
        sat_time = stats["summary"]["times"].get("sat", 0)
        unsat_time = stats["summary"]["times"].get("unsat", 0)
        cpu_time = stats["summary"]["times"]["cpu"]

        lines.extend(
            (
                f"Time         : {total_time:.3f}s (Solving: {solving_time:.3f}s "
                f"1st Model: {sat_time:.3f}s Unsat: {unsat_time:.3f}s)",
                f"CPU Time     : {cpu_time:.3f}s",
                "",
            )
        )

        # Choices and Conflicts
        choices = int(stats["solving"]["solvers"]["choices"])
        conflicts = int(stats["solving"]["solvers"]["conflicts"])
        conflicts_analyzed = int(stats["solving"]["solvers"]["conflicts_analyzed"])

        lines.extend(
            (
                f"Choices      : {choices}",
                f"Conflicts    : {conflicts:<8} (Analyzed: {conflicts_analyzed})",
            )
        )
        # Restarts
        restarts = int(stats["solving"]["solvers"]["restarts"])
        restarts_last = int(stats["solving"]["solvers"]["restarts_last"])
        restarts_blocked = int(stats["solving"]["solvers"]["restarts_blocked"])
        avg_restart = (conflicts_analyzed / restarts) if restarts > 0 else 0

        lines.append(
            f"Restarts     : {restarts:<8} (Average: {avg_restart:5.2f} "
            f"Last: {restarts_last} Blocked: {restarts_blocked})"
        )

        # Model-Level and Problems
        extra = stats["solving"]["solvers"].get("extra", {})
        if "models_level" in extra:
            model_level = extra["models_level"]
            lines.append(f"Model-Level  : {model_level}")

        # Problems section
        splits = int(extra.get("splits", 0))
        problems = 1  # Assuming single problem for now
        avg_length = 1.00  # This might need to be calculated differently
        lines.append(f"Problems     : {problems:<8} (Average Length: {avg_length:.2f} Splits: {splits})")

        # Enhanced Lemmas section (replace your current lemma section with this):
        if "lemmas" in extra:
            lemmas_total = int(extra["lemmas"])
            lemmas_conflict = int(extra.get("lemmas_conflict", 0))
            lemmas_loop = int(extra.get("lemmas_loop", 0))
            lemmas_binary = int(extra.get("lemmas_binary", 0))
            lemmas_ternary = int(extra.get("lemmas_ternary", 0))
            lemmas_other = int(extra.get("lemmas_other", 0))
            lemmas_deleted = int(extra.get("lemmas_deleted", 0))

            # Calculate ratios
            binary_ratio = (lemmas_binary / lemmas_total * 100) if lemmas_total > 0 else 0
            ternary_ratio = (lemmas_ternary / lemmas_total * 100) if lemmas_total > 0 else 0
            conflict_ratio = (lemmas_conflict / lemmas_total * 100) if lemmas_total > 0 else 0
            loop_ratio = (lemmas_loop / lemmas_total * 100) if lemmas_total > 0 else 0
            other_ratio = (lemmas_other / lemmas_total * 100) if lemmas_total > 0 else 0

            # Calculate average lengths
            lits_conflict = int(extra.get("lits_conflict", 0))
            lits_loop = int(extra.get("lits_loop", 0))
            lits_other = int(extra.get("lits_other", 0))

            avg_conflict_length = (lits_conflict / lemmas_conflict) if lemmas_conflict > 0 else 0
            avg_loop_length = (lits_loop / lemmas_loop) if lemmas_loop > 0 else 0
            avg_other_length = (lits_other / lemmas_other) if lemmas_other > 0 else 0

            lines.extend(
                (
                    f"Lemmas       : {lemmas_total:<8} (Deleted: {lemmas_deleted})",
                    f"  Binary     : {lemmas_binary:<8} (Ratio: {binary_ratio:6.2f}%)",
                    f"  Ternary    : {lemmas_ternary:<8} (Ratio: {ternary_ratio:6.2f}%)",
                    f"  Conflict   : {lemmas_conflict:<8} (Average Length: {avg_conflict_length:6.1f} "
                    f"Ratio: {conflict_ratio:6.2f}%)",
                    f"  Loop       : {lemmas_loop:<8} (Average Length: {avg_loop_length:6.1f} "
                    f"Ratio: {loop_ratio:6.2f}%)",
                    f"  Other      : {lemmas_other:<8} (Average Length: {avg_other_length:6.1f} "
                    f"Ratio: {other_ratio:6.2f}%)",
                )
            )

        # Backjumps section
        jumps_data = extra.get("jumps", {})
        if jumps_data:
            total_jumps = int(jumps_data.get("jumps", 0))
            total_levels = int(jumps_data.get("levels", 0))
            max_jump = int(jumps_data.get("max", 0))
            bounded_jumps = int(jumps_data.get("jumps_bounded", 0))
            bounded_levels = int(jumps_data.get("levels_bounded", 0))
            max_bounded = int(jumps_data.get("max_bounded", 0))

            # Calculate executed jumps
            executed_jumps = total_jumps - bounded_jumps
            executed_levels = total_levels - bounded_levels
            max_executed = int(jumps_data.get("max_executed", max_jump))

            # Calculate averages
            # Note: there seems to be a bug in clasp's calculation of avg_executed jumps
            # I opened a bug report: https://github.com/potassco/clasp/issues/111
            avg_total = (total_levels / total_jumps) if total_jumps > 0 else 0
            avg_executed = (executed_levels / executed_jumps) if executed_jumps > 0 else 0
            avg_bounded = (bounded_levels / bounded_jumps) if bounded_jumps > 0 else 0

            # Calculate ratios
            executed_ratio = (executed_levels / total_levels * 100) if total_levels > 0 else 0
            bounded_ratio = (bounded_levels / total_levels * 100) if total_levels > 0 else 0

            lines.extend(
                (
                    f"Backjumps    : {total_jumps:<8} (Average: {avg_total:5.2f} Max: {max_jump:3d} "
                    f"Sum: {total_levels:6d})",
                    f"  Executed   : {executed_jumps:<8} (Average: {avg_executed:5.2f} Max: {max_executed:3d} "
                    f"Sum: {executed_levels:6d} Ratio: {executed_ratio:6.2f}%)",
                    f"  Bounded    : {bounded_jumps:<8} (Average: {avg_bounded:5.2f} Max: {max_bounded:3d} "
                    f"Sum: {bounded_levels:6d} Ratio: {bounded_ratio:6.2f}%)",
                    "",  # Empty line before Rules section
                )
            )

        # Rules
        rules_original = int(stats["problem"]["lp"]["rules"])
        rules_transformed = int(stats["problem"]["lp"]["rules_tr"])
        choice_rules = int(stats["problem"]["lp"]["rules_choice"])

        lines.extend(
            (
                f"Rules        : {rules_transformed:<8} (Original: {rules_original})",
                f"  Choice     : {choice_rules}",
            )
        )

        # Atoms - show original and auxiliary breakdown like clingo
        atoms_total = int(stats["problem"]["lp"]["atoms"])
        atoms_aux = int(stats["problem"]["lp"]["atoms_aux"])
        atoms_original = atoms_total - atoms_aux

        if atoms_aux > 0:
            lines.append(f"Atoms        : {atoms_total:<8} (Original: {atoms_original} Auxiliary: {atoms_aux})")
        else:
            lines.append(f"Atoms        : {atoms_total:<8}")

        # Bodies
        bodies_original = int(stats["problem"]["lp"]["bodies"])
        bodies_transformed = int(stats["problem"]["lp"]["bodies_tr"])
        count_bodies_original = int(stats["problem"]["lp"]["count_bodies"])
        count_bodies_transformed = int(stats["problem"]["lp"]["count_bodies_tr"])

        lines.extend(
            (
                f"Bodies       : {bodies_transformed:<8} (Original: {bodies_original})",
                f"  Count      : {count_bodies_transformed:<8} (Original: {count_bodies_original})",
            )
        )

        # Equivalences
        eqs_total = int(stats["problem"]["lp"]["eqs"])
        eqs_atom = int(stats["problem"]["lp"]["eqs_atom"])
        eqs_body = int(stats["problem"]["lp"]["eqs_body"])
        eqs_other = int(stats["problem"]["lp"]["eqs_other"])

        lines.append(f"Equivalences : {eqs_total:<8} (Atom=Atom: {eqs_atom} Body=Body: {eqs_body} Other: {eqs_other})")

        # Tight
        sccs = int(stats["problem"]["lp"]["sccs"])
        sccs_non_hcf = int(stats["problem"]["lp"]["sccs_non_hcf"])
        ufs_nodes = int(stats["problem"]["lp"]["ufs_nodes"])
        gammas = int(stats["problem"]["lp"]["gammas"])
        tight = "Yes" if sccs == 0 else "No"

        lines.append(
            f"Tight        : {tight:<8} (SCCs: {sccs} Non-Hcfs: {sccs_non_hcf} Nodes: {ufs_nodes} Gammas: {gammas})"
        )

        # Variables
        vars_total = int(stats["problem"]["generator"]["vars"])
        vars_eliminated = int(stats["problem"]["generator"]["vars_eliminated"])
        vars_frozen = int(stats["problem"]["generator"]["vars_frozen"])

        lines.append(f"Variables    : {vars_total:<8} (Eliminated: {vars_eliminated:4d} Frozen: {vars_frozen})")

        # Constraints
        # Total constraints = binary + ternary + other
        constraints_binary = int(stats["problem"]["generator"]["constraints_binary"])
        constraints_ternary = int(stats["problem"]["generator"]["constraints_ternary"])
        constraints_other = int(stats["problem"]["generator"]["constraints"])
        constraints_total = constraints_binary + constraints_ternary + constraints_other

        if constraints_total > 0:
            binary_pct = (constraints_binary / constraints_total) * 100
            ternary_pct = (constraints_ternary / constraints_total) * 100
            other_pct = (constraints_other / constraints_total) * 100

            lines.append(
                f"Constraints  : {constraints_total:<8} (Binary: {binary_pct:5.1f}% "
                f"Ternary: {ternary_pct:5.1f}% Other: {other_pct:5.1f}%)"
            )
        else:
            lines.append("Constraints  : 0")

        return "\n".join(lines)
