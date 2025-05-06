import importlib
import json
import pprint
from abc import ABC, abstractmethod
from typing import Any

from aspuzzle.grids.base import Grid, GridCellData
from aspuzzle.puzzle import Puzzle


class Solver(ABC):
    default_config: dict[str, Any] = {}
    solver_name: str = "Puzzle solver"
    supported_grid_types: list[str] = ["RectangularGrid"]  # Default supported grid type
    supported_symbols: list[str | int] = []  # List of supported symbols in the grid definition
    map_grid_to_integers: bool = False  # Controls how the grid is read
    _grid_data: list[GridCellData] | None = None

    def __init__(self, puzzle: Puzzle, config: dict[str, Any]) -> None:
        self.puzzle = puzzle
        self.puzzle.name = self.solver_name
        # Merge default config with instance config
        self.config = {**self.default_config, **config}

        self.create_grid()

    def create_grid(self) -> None:
        """Create the grid for this puzzle. Can be overridden by subclasses."""
        grid_type = self.config.get("grid_type", "RectangularGrid")

        # Check if the specified grid type is supported
        if grid_type not in self.supported_grid_types:
            supported = ", ".join(self.supported_grid_types)
            raise ValueError(
                f"Grid type '{grid_type}' is not supported by {self.solver_name}. Supported types: {supported}"
            )

        # Import the grid class dynamically
        try:
            grid_module = importlib.import_module(f"aspuzzle.grids.{grid_type.lower()}")
            grid_class = getattr(grid_module, grid_type)
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Failed to import grid type {grid_type}: {e}") from e

        # Let the grid create itself from the config
        self.grid = grid_class.from_config(self.puzzle, self.config)

        # After grid is created, parse the grid data if available
        if "grid" in self.config and self.grid is not None:
            self._grid_data = self.grid.parse_grid(self.config["grid"], map_to_integers=self.map_grid_to_integers)

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

    @property
    def unpack_data(self) -> tuple[Puzzle, Grid, dict[str, Any], list[tuple[int, int, int | str]]]:
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
        for r, row in enumerate(self.config["grid"]):
            for c, symbol in enumerate(row):
                if symbol.isdigit():
                    symbol = int(symbol)
                if symbol not in self.supported_symbols:
                    raise ValueError(
                        f"Unsupported symbol '{symbol}' at position ({r + 1}, {c + 1}). "
                        f"Supported symbols: {', '.join(str(s) for s in self.supported_symbols)}"
                    )

    def validate_config(self) -> None:
        """Function to perform extra validation on the puzzle config as needed."""
        pass

    @abstractmethod
    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""

    def solve(self) -> None:
        """Solve the puzzle."""
        # Render the puzzle
        print(self.puzzle.render())

        # Gather all solutions
        solutions = []
        for solution in self.puzzle.solve():
            solution_dict = {
                predicate_name: sorted(list(instances), key=str) for predicate_name, instances in solution.items()
            }
            solutions.append(solution_dict)

        # Print results
        print("\n=== Solutions ===")
        if not self.puzzle.satisfiable:
            print("No solutions found")
        else:
            print(json.dumps(solutions[:2], indent=2, default=str))
            if len(solutions) > 2:
                print(f"(... suppressed ({len(solutions) - 2} more)")

            # Print solution count
            suffix = "(exhausted)" if self.puzzle.exhausted else "(not exhausted)"
            if self.puzzle.solution_count == 1:
                print(f"\n1 solution found {suffix}")
            else:
                print(f"\n{self.puzzle.solution_count} solutions found {suffix}")

        # Print statistics
        print("\n=== Statistics ===")
        pprint.pprint(self.puzzle.statistics)

        # Validate solutions against expected solutions if provided
        if "solutions" in self.config:
            print("\n=== Solution Validation ===")
            expected_solutions = self.config["solutions"]

            # Convert found solutions to comparable format (sets of frozensets)
            found_solutions_set = set()
            for sol in solutions:
                # Convert each solution to a frozenset of (predicate_name, frozenset of predicates)
                solution_set = frozenset(
                    (pred_name, frozenset(str(pred) for pred in preds)) for pred_name, preds in sol.items()
                )
                found_solutions_set.add(solution_set)

            # Convert expected solutions to the same format
            expected_solutions_set = set()
            for expected_solution in expected_solutions:
                solution_set = frozenset(
                    (pred_name, frozenset(preds)) for pred_name, preds in expected_solution.items()
                )
                expected_solutions_set.add(solution_set)

            # Compare the sets
            if found_solutions_set == expected_solutions_set:
                count = len(expected_solutions)
                if count == 1:
                    print("✓ The expected solution was found")
                else:
                    print(f"✓ All {count} expected solutions were found")
            else:
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
