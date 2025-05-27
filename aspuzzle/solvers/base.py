from __future__ import annotations

import importlib
import json
from abc import ABC, abstractmethod
from typing import Any

from aspuzzle.grids.base import Grid, GridCellData
from aspuzzle.grids.rendering import RenderItem
from aspuzzle.puzzle import Puzzle
from pyclingo import Predicate


class Solver(ABC):
    default_config: dict[str, Any] = {}
    solver_name: str = "Puzzle solver"
    supported_grid_types: tuple[type] = (Grid,)  # Support all grids by default
    supported_symbols: list[str | int] = []  # List of supported symbols in the grid definition
    grid: Grid
    map_grid_to_integers: bool = False  # Whether to map grid symbols to unique integer ids, useful for defining regions
    _grid_data: list[GridCellData] | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Solver:
        """
        Create and return the appropriate Solver subclass instance for the given configuration.

        Args:
            config: The puzzle configuration dictionary

        Returns:
            An initialized Solver subclass instance

        Raises:
            ValueError: If the puzzle_type is missing or invalid
        """
        if "puzzle_type" not in config:
            raise ValueError("Puzzle configuration must include 'puzzle_type'")

        puzzle_type = config["puzzle_type"]

        # Import the solver module dynamically
        try:
            module = importlib.import_module(f"aspuzzle.solvers.{puzzle_type.lower()}")
            puzzle_class = getattr(module, puzzle_type)
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Invalid puzzle type '{puzzle_type}': {e}") from e

        # Verify that the class is a Solver subclass
        if not issubclass(puzzle_class, cls):
            raise ValueError(f"Class '{puzzle_type}' is not a Solver subclass")

        # Initialize and return the solver
        puzzle = puzzle_class(config)
        assert isinstance(puzzle, Solver)
        return puzzle

    def __init__(self, config: dict[str, Any]) -> None:
        self.puzzle = Puzzle()
        self.puzzle.name = self.solver_name
        # Merge default config with instance config
        self.config = {**self.default_config, **config}

        self.create_grid()
        _ = self.grid_data  # Preprocess this so it's ready!
        self.validate()
        self._preprocess_config()

    def create_grid(self) -> None:
        """Create the grid for this puzzle. Can be overridden by subclasses."""
        grid_type_name = self.config.get("grid_type", "RectangularGrid")

        # Import the grid class dynamically
        try:
            grid_module = importlib.import_module(f"aspuzzle.grids.{grid_type_name.lower()}")
            grid_class = getattr(grid_module, grid_type_name)
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Failed to import grid type {grid_type_name}: {e}") from e

        # Check if the imported grid class is supported based on type inheritance
        if not issubclass(grid_class, self.supported_grid_types):
            supported_names = ", ".join(t.__name__ for t in self.supported_grid_types)
            raise ValueError(
                f"Grid type '{grid_type_name}' is not supported by {self.solver_name}. "
                f"Supported types: {supported_names}"
            )

        # Let the grid create itself from the config
        assert issubclass(grid_class, Grid)
        self.grid = grid_class.from_config(self.puzzle, self.config)

    @property
    def grid_data(self) -> list[GridCellData]:
        """
        Get the parsed grid data, using the provided mapping strategy.
        Lazy-loads and caches the data on first access.

        Returns:
            The parsed grid data
        """
        if self._grid_data is None:
            if "grid" not in self.config:
                self._grid_data = []
            else:
                self._grid_data = self.grid.parse_grid(self.config["grid"], map_to_integers=self.map_grid_to_integers)
        assert self._grid_data is not None
        return self._grid_data

    def _preprocess_config(self) -> None:
        """
        Optional preprocessing step after config validation and grid data parsing.

        This method is called after validate_config() and grid_data property access
        in __init__. Subclasses can override this to perform additional preprocessing
        such as region coloring computation.
        """
        pass

    def unpack_data(self) -> tuple[Puzzle, Grid, dict[str, Any], list[GridCellData]]:
        """
        Convenience property to get puzzle, grid, config, and parsed grid data.

        Returns:
            A tuple containing (puzzle, grid, config, grid_data)
        """
        return self.puzzle, self.grid, self.config, self.grid_data

    def validate(self) -> None:
        """Validate the puzzle configuration."""
        self.validate_grid_symbols()
        self.validate_config()

    def validate_grid_symbols(self) -> None:
        """Validate that the grid contains only supported symbols."""
        if not self.supported_symbols or "grid" not in self.config:
            return  # Nothing to validate

        # Check each cell against supported symbols
        for loc, symbol in self.grid_data:
            if symbol not in self.supported_symbols:
                raise ValueError(
                    f"Unsupported symbol '{symbol}' at position {loc}. "
                    f"Supported symbols: {', '.join(str(s) for s in self.supported_symbols)}"
                )

    def validate_config(self) -> None:
        """Function to perform extra validation on the puzzle config as needed."""
        pass

    @abstractmethod
    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""

    def solve(self, models: int = 0, timeout: int = 0) -> list[dict]:
        """Solve the puzzle and return the results."""
        self.puzzle.finalize()

        solutions = []
        for solution in self.puzzle.solve(models=models, timeout=timeout):
            solution_dict = {
                predicate_name: sorted(list(instances), key=str) for predicate_name, instances in solution.items()
            }
            solutions.append(solution_dict)

        return solutions

    def display_results(self, solutions: list[dict], visualize: bool = True) -> None:
        """Display the solving results."""
        print("\n=== Solutions ===")
        if not self.puzzle.satisfiable:
            print("No solutions found")
        else:
            print(json.dumps(solutions[:2], indent=2, default=repr))
            if len(solutions) > 2:
                print(f"(... suppressed ({len(solutions) - 2} more)")

            # Visualize the first couple of solutions if requested
            if visualize and solutions:
                for idx, sol in enumerate(solutions[:2]):
                    print(f"\nSolution {idx + 1}:")
                    print(self.render_puzzle(sol))

            # Print solution count
            suffix = "(exhausted)" if self.puzzle.exhausted else "(not exhausted)"
            if self.puzzle.solution_count == 1:
                print(f"\n1 solution found {suffix}")
            else:
                print(f"\n{self.puzzle.solution_count} solutions found {suffix}")

    def display_statistics(self) -> None:
        """Display statistics after solving."""
        formatted_stats = self.puzzle.format_statistics_clingo_style()
        print("\n=== Statistics ===")
        print(formatted_stats)

    def validate_solutions(self, solutions: list[dict]) -> bool:
        """Validate that solutions found match expected solutions."""
        if "solutions" not in self.config:
            return True

        print("\n=== Solution Validation ===")
        expected_solutions = self.config["solutions"]

        # Convert found solutions to comparable format (sets of frozensets)
        found_solutions_set = set()
        for sol in solutions:
            # Convert each solution to a frozenset of (predicate_name, frozenset of predicates)
            solution_set = frozenset(
                (pred_name, frozenset(repr(pred) for pred in preds)) for pred_name, preds in sol.items()
            )
            found_solutions_set.add(solution_set)

        # Convert expected solutions to the same format
        expected_solutions_set = set()
        for expected_solution in expected_solutions:
            solution_set = frozenset((pred_name, frozenset(preds)) for pred_name, preds in expected_solution.items())
            expected_solutions_set.add(solution_set)

        # Compare the sets
        if found_solutions_set == expected_solutions_set:
            count = len(expected_solutions)
            if count == 1:
                print("✓ The expected solution was found")
            else:
                print(f"✓ All {count} expected solutions were found")
            return True

        print("✗ Solutions do not match expected")

        # Find differences
        missing_solutions = expected_solutions_set - found_solutions_set
        extra_solutions = found_solutions_set - expected_solutions_set

        if missing_solutions:
            self._print_solution_diff(
                missing_solutions,
                count_label="Missing",
                item_label="Missing solution",
            )

        if extra_solutions:
            self._print_solution_diff(
                extra_solutions, count_label="Found", item_label="Extra solution", suffix=" unexpected"
            )

        return False

    @staticmethod
    def _print_solution_diff(solutions: set, count_label: str, item_label: str, suffix: str = "") -> None:
        """Print differences between expected and found solutions."""
        count = len(solutions)
        print(f"  {count_label} {count}{suffix} solution{'s' if count != 1 else ''}")

        # Show up to 2 examples
        for i, sol in enumerate(solutions, 1):
            if i > 2:
                break
            print(f"    {item_label} {i}:")
            # Convert back to readable format
            sol_dict = {pred_name: sorted(list(preds)) for pred_name, preds in sol}
            print(json.dumps(sol_dict, indent=6, default=str))

        # Show suppression message if needed
        if count > 2:
            print(f"    (... suppressed {count - 2} more)")

    def render_puzzle(self, solution: dict[str, list[Predicate]] | None = None) -> str:
        """
        Render a solution as ASCII text.

        Args:
            solution: Solution dictionary mapping predicate names to lists of predicate instances

        Returns:
            ASCII representation of the solution
        """
        # Perform any additional preprocessing before rendering
        self._preprocess_for_rendering(solution)

        # Preprocess puzzle symbols and predicates
        puzzle_render_items = self._preprocess_puzzle_symbols()
        predicate_render_items = self._preprocess_predicates(solution)

        # Get rendering configuration
        render_config = self.get_render_config()

        # Call the grid's render_ascii method with processed items
        return self.grid.render_ascii(
            puzzle_render_items=puzzle_render_items,
            predicate_render_items=predicate_render_items,
            render_config=render_config,
        )

    def _preprocess_puzzle_symbols(self) -> list[RenderItem]:
        """
        Preprocess puzzle definition symbols for rendering.

        Returns:
            List of RenderItem objects ready for rendering
        """
        render_config = self.get_render_config()
        puzzle_symbols = render_config.get("puzzle_symbols", {})

        processed_symbols = []

        for loc, value in self.grid_data:
            symbol_config = puzzle_symbols.get(value)
            if symbol_config is None:
                continue
            assert isinstance(symbol_config, dict)

            display_symbol = symbol_config.get("symbol", str(value))
            foreground_color = symbol_config.get("color", None)
            background_color = symbol_config.get("background", None)

            render_item = RenderItem(
                loc=self.grid.Cell(*loc), symbol=display_symbol, color=foreground_color, background=background_color
            )
            processed_symbols.append(render_item)

        return processed_symbols

    def _preprocess_predicates(self, solution: dict[str, list[Predicate]] | None = None) -> dict[int, list[RenderItem]]:
        """
        Preprocess solution predicates for rendering, organized by priority level.

        Args:
            solution: Dictionary mapping predicate names to lists of predicate instances

        Returns:
            Dictionary mapping priority levels to lists of RenderItem objects
        """
        if not solution:
            return {}

        render_config = self.get_render_config()
        predicate_styling = render_config.get("predicates", {})

        priority_render_items: dict[int, list[RenderItem]] = {}

        for pred_name, instances in solution.items():
            render_info = predicate_styling.get(pred_name)
            if render_info is None:
                continue
            assert isinstance(render_info, dict)

            priority = render_info.get("priority", 0)

            # Initialize list for this priority if needed
            if priority not in priority_render_items:
                priority_render_items[priority] = []

            if custom_renderer := render_info.get("custom_renderer"):
                priority_render_items[priority].extend([item for pred in instances for item in custom_renderer(pred)])
            else:
                color = render_info.get("color", None)
                background = render_info.get("background", None)
                default_symbol = render_info.get("symbol", pred_name[0])
                value_field: str | None = render_info.get("value", None)

                for pred in instances:
                    if render_info.get("loop_directions"):
                        # Handle loop directions
                        dir1_field = render_info.get("dir1_field", "dir1")
                        dir2_field = render_info.get("dir2_field", "dir2")
                        dir1 = pred[dir1_field].value
                        dir2 = pred[dir2_field].value
                        combined = dir1 + dir2
                        symbol = self.grid.line_characters.get(combined, None)
                    elif value_field is not None:
                        # Handle value field
                        symbol = str(pred[value_field])
                    else:
                        # Use default symbol
                        symbol = default_symbol

                    priority_render_items[priority].append(
                        RenderItem(
                            loc=pred["loc"],
                            symbol=symbol,
                            color=color,
                            background=background,
                        )
                    )

        return priority_render_items

    def _preprocess_for_rendering(self, solution: dict[str, list[Predicate]] | None = None) -> None:
        """
        Optional preprocessing step before rendering. Intended to be used to cache calculations that can be used in
        get_rendering_config.
        """
        pass

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for this solver.

        This is a default implementation that provides no special rendering.
        Solver subclasses should override this method to provide specific rendering configuration.

        Returns:
            Dictionary with rendering configuration
        """
        return {
            "puzzle_symbols": {},  # Map puzzle values to display symbols
            "predicates": {},  # Map predicate names to rendering info
        }

    def validate_line_clues(self) -> None:
        """
        Validates that all expected line clues exist and have the correct length.

        Raises:
            ValueError: If required clue lists are missing or have incorrect length
        """
        grid = self.grid

        for direction in grid.line_direction_names:
            clue_key = f"{grid.line_direction_descriptions[direction]}_clues"

            # Check if clues exist
            if clue_key not in self.config:
                raise ValueError(f"Missing {clue_key} in puzzle configuration")

            # Check if count matches grid size
            expected_count = grid.get_line_count(direction)
            actual_count = len(self.config[clue_key])

            if actual_count != expected_count:
                raise ValueError(f"Expected {expected_count} {clue_key}, got {actual_count}")
