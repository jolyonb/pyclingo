from __future__ import annotations

from typing import Callable, Generator, Type, Any, TypeVar

from pyclingo import ASPProgram, Predicate
from pyclingo.term import Term
from pyclingo.value import SymbolicConstant


class Puzzle:
    """
    Coordinates modules and their rules to create a complete ASP program.

    The Puzzle class provides a high-level interface for defining logic puzzles
    using pyclingo, with support for modular organization.
    """

    def __init__(self, name: str = "puzzle"):
        """
        Initialize a new puzzle.

        Args:
            name: A name for this puzzle (for documentation purposes)
        """
        self.name = name
        self._program = ASPProgram()
        self._modules: dict[str, Module] = {}

    def get_module(self, name: str) -> Module:
        """
        Get a module by name.

        Args:
            name: The name of the module to retrieve

        Returns:
            The requested module

        Raises:
            KeyError: If no module with the given name exists
        """
        if name not in self._modules:
            raise KeyError(f"No module named '{name}' is registered")
        return self._modules[name]

    def register_module(self, module: Module) -> None:
        """
        Register a module with this puzzle.

        Args:
            module: The module to register

        Raises:
            ValueError: If a module with the same name is already registered
        """
        if module.name in self._modules:
            raise ValueError(f"Module with name '{module.name}' is already registered")

        self._modules[module.name] = module
        self._program.add_segment(module.name)

    # Forward methods to ASPProgram with segment
    def fact(self, *predicates: Predicate, segment: str = "default") -> None:
        """
        Add one or more unconditional facts to the program.

        Args:
            *predicates: One or more predicate instances to add as facts
            segment: The segment to add these facts to (default: "default")
        """
        self._program.fact(*predicates, segment=segment)

    def when(
        self, conditions: Term | list[Term], let: Term, segment: str = "default"
    ) -> None:
        """
        Create a rule which sets the 'let' term when all conditions are satisfied.

        Args:
            conditions: One or more conditions that must be satisfied
            let: The term that becomes true when conditions are met
            segment: The segment to add this rule to (default: "default")
        """
        self._program.when(conditions, let, segment=segment)

    def forbid(self, *conditions: Term, segment: str = "default") -> None:
        """
        Create a constraint which forbids the specified combination of conditions.

        Args:
            *conditions: One or more conditions that must not be simultaneously satisfied
            segment: The segment to add this constraint to (default: "default")
        """
        self._program.forbid(*conditions, segment=segment)

    def comment(self, text: str, segment: str = "default") -> None:
        """
        Add a comment to the program.

        Args:
            text: The comment text
            segment: The segment to add this comment to (default: "default")
        """
        self._program.comment(text, segment=segment)

    def blank_line(self, segment: str = "default") -> None:
        """
        Add a blank line to the program for formatting.

        Args:
            segment: The segment to add this blank line to (default: "default")
        """
        self._program.blank_line(segment=segment)

    def section(self, title: str, segment: str = "default") -> None:
        """
        Add a section header to the program.

        Args:
            title: The section title
            segment: The segment to add this section header to (default: "default")
        """
        self._program.section(title, segment=segment)

    def register_symbolic_constant(
        self, name: str, value: int | str
    ) -> SymbolicConstant:
        """
        Register a symbolic constant with the program.

        Args:
            name: The name of the constant
            value: The value of the constant (integer or string)

        Returns:
            A SymbolicConstant object that can be used in ASP rules

        Raises:
            ValueError: If the name is invalid or already registered
            TypeError: If the value is not an integer or string
        """
        return self._program.register_symbolic_constant(name, value)

    def solve(
        self, models: int = 0, timeout: int = 0
    ) -> Generator[dict[Type[Predicate], set[Predicate]], None, None]:
        """
        Solve the puzzle and yield solutions.

        Args:
            models: Maximum number of models to compute (0 for all)
            timeout: Timeout in seconds (0 for no timeout)

        Yields:
            For each solution, a dictionary mapping Predicate types to sets of Predicate instances

        Notes:
            After all models are yielded, solver statistics are stored in the
            underlying ASPProgram's 'statistics' attribute.
        """
        yield from self._program.solve(models=models, timeout=timeout)

    @property
    def satisfiable(self) -> bool | None:
        """Whether the puzzle has at least one solution."""
        return self._program.satisfiable

    @property
    def model_count(self) -> int | None:
        """The number of models found, or None if not solved yet."""
        return self._program.model_count

    @property
    def statistics(self) -> dict[str, int] | None:
        """Solver statistics after solving, or None if not solved yet."""
        return self._program.statistics

    def render(self) -> str:
        """
        Render the puzzle as an ASP program.

        Returns:
            str: The rendered ASP program.
        """
        return self._program.render()


class Module:
    """
    Base class for puzzle modules.

    Modules provide organization and domain-specific logic for different
    components of a puzzle. Each module has its own namespace in the ASP program.
    """

    def __init__(self, puzzle: Puzzle, name: str):
        """
        Initialize a module.

        Args:
            puzzle: The puzzle this module belongs to
            name: The name of this module (used as the segment name)
        """
        if type(self) == Module:
            raise ValueError("Cannot instantiate an abstract Module object")

        self._puzzle = puzzle
        self._name = name

        # Register with the puzzle
        puzzle.register_module(self)

    @property
    def name(self) -> str:
        """Get the name of this module."""
        return self._name

    @property
    def puzzle(self) -> Puzzle:
        """Get the puzzle this module belongs to."""
        return self._puzzle

    # Methods that automatically use this module's segment

    def fact(self, *predicates: Predicate) -> None:
        """
        Add one or more unconditional facts to this module's segment.

        Args:
            *predicates: One or more predicate instances to add as facts
        """
        self._puzzle.fact(*predicates, segment=self._name)

    def when(self, conditions: Term | list[Term], let: Term) -> None:
        """
        Create a rule in this module's segment.

        Args:
            conditions: One or more conditions that must be satisfied
            let: The term that becomes true when conditions are met
        """
        self._puzzle.when(conditions, let, segment=self._name)

    def forbid(self, *conditions: Term) -> None:
        """
        Create a constraint in this module's segment.

        Args:
            *conditions: One or more conditions that must not be simultaneously satisfied
        """
        self._puzzle.forbid(*conditions, segment=self._name)

    def comment(self, text: str) -> None:
        """
        Add a comment to this module's segment.

        Args:
            text: The comment text
        """
        self._puzzle.comment(text, segment=self._name)

    def blank_line(self) -> None:
        """Add a blank line to this module's segment for formatting."""
        self._puzzle.blank_line(segment=self._name)

    def section(self, title: str) -> None:
        """
        Add a section header to this module's segment.

        Args:
            title: The section title
        """
        self._puzzle.section(title, segment=self._name)


T = TypeVar("T")


def cached_predicate(init_func: Callable[[Any], T]) -> property:
    """
    Decorator for caching predicates in Module classes.

    This decorator will cache predicate definitions and only execute their initialization
    logic the first time they are accessed.

    Args:
        init_func: The property function that initializes and returns the predicate

    Returns:
        A wrapped property that caches the predicate after first access
    """
    attr_name = f"_{init_func.__name__}"

    def getter(self: Any) -> T:
        # Check if the predicate has already been initialized
        if not hasattr(self, attr_name) or getattr(self, attr_name) is None:
            # Initialize the predicate and store it
            setattr(self, attr_name, init_func(self))

        # Return the cached predicate
        return getattr(self, attr_name)

    return property(getter)


# TODO: Add puzzle name header (requires creating header in ASPProgram)
