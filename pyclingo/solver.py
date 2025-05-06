from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Generator

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
    statistics: dict[str, int | float] | None = None

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

    def when(self, conditions: Term | list[Term], let: Term, segment: str | None = None) -> None:
        """Create a clingo rule which sets the let term when all conditions are satisfied."""
        condition_list = conditions if isinstance(conditions, list) else [conditions]
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
    ) -> Generator[dict[str, set[Predicate]], None, None]:
        """
        Solve the ASP program and yield solutions as sets of Predicate objects.

        Args:
            models: Maximum number of models to compute (0 for all)
            timeout: Timeout in seconds (0 for no timeout)
            stop_on_log_level: Log level at which to abort solving

        Yields:
            For each solution, a dictionary mapping Predicate types to sets of Predicate instances

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
        control = clingo.Control(logger=message_handler.on_message)
        assert isinstance(control.configuration.solve, clingo.Configuration)
        control.configuration.solve.models = models or 1000  # Maximum of 1000 rather than unlimited
        if timeout > 0:
            control.configuration.solve.timeout = timeout

        # Get a mapping of predicate names to their types for reconstruction
        predicate_types = {pred.get_name(): pred for pred in self._collect_predicates()}

        # Add and ground the program
        control.add("base", [], asp_source)

        try:
            control.ground([("base", [])])
        except RuntimeError as e:
            # Handle grounding errors
            error_msg = f"Grounding failed: {e}\n\n"
            if formatted_messages := message_handler.format_all_messages():
                error_msg += formatted_messages
            raise RuntimeError(error_msg) from e

        # Check for messages after grounding
        if message_handler.messages:
            print(message_handler.format_all_messages())

            # Check if we should halt based on log level
            if message_handler.should_halt:
                assert message_handler.highest_level is not None
                raise RuntimeError(
                    f"Grounding produced {message_handler.highest_level.name} level messages "
                    f"(stop threshold: {stop_on_log_level.name})."
                )

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

        # Store statistics after solving is complete
        self.statistics = {
            "atoms": int(control.statistics["problem"]["lp"]["atoms"]),
            "rules": int(control.statistics["problem"]["lp"]["rules_tr"]),
            "variables": int(control.statistics["problem"]["generator"]["vars"]),
            "constraints": int(control.statistics["problem"]["generator"]["complexity"]),
            "choices": int(control.statistics["solving"]["solvers"]["choices"]),
            "conflicts": int(control.statistics["solving"]["solvers"]["conflicts"]),
            "normal_rules": int(control.statistics["problem"]["lp"]["rules_normal"]),
            "choice_rules": int(control.statistics["problem"]["lp"]["rules_choice"]),
            "binary_constraints": int(control.statistics["problem"]["generator"]["constraints_binary"]),
            "ternary_constraints": int(control.statistics["problem"]["generator"]["constraints_ternary"]),
            "total_time": toc - tic,
            "grounding_time": (
                control.statistics["summary"]["times"]["total"] - control.statistics["summary"]["times"]["solve"]
            ),
            "solving_time": control.statistics["summary"]["times"]["solve"],
        }

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
    ) -> dict[str, set[Predicate]]:
        """
        Convert a clingo model to a dictionary of Predicate objects.

        Args:
            model: A clingo model containing symbols
            predicate_types: Dictionary mapping predicate names to Predicate classes

        Returns:
            Dictionary mapping Predicate types to sets of Predicate instances
        """
        result = defaultdict(set)

        for symbol in model.symbols(shown=True):
            pred_instance = self._convert_symbol_to_predicate(symbol, predicate_types)
            result[pred_instance.get_name()].add(pred_instance)

        return dict(result)
