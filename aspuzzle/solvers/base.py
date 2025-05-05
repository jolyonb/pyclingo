import importlib
import json
import pprint
from typing import Any

from aspuzzle.grids.base import Grid
from aspuzzle.puzzle import Puzzle


class Solver:
    default_config: dict[str, Any] = {}
    solver_name: str = "Puzzle solver"
    supported_grid_types: list[str] = ["RectangularGrid"]  # Default supported grid type

    def __init__(self, puzzle: Puzzle, config: dict[str, Any]) -> None:
        self.puzzle = puzzle
        self.puzzle.name = self.solver_name
        self.grid = None
        # Merge default config with instance config
        self.config = {**self.default_config, **config}

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

        # Create the grid
        self.grid = grid_class(self.puzzle, **self.config["grid_params"])

    @property
    def pgc(self) -> tuple[Puzzle, Grid, dict[str, Any]]:
        """Convenience property to get puzzle, grid, and config."""
        return self.puzzle, self.grid, self.config

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
            for solution in solutions:
                # Convert each solution to a frozenset of (predicate_name, frozenset of predicates)
                solution_set = frozenset(
                    (pred_name, frozenset(str(pred) for pred in preds)) for pred_name, preds in solution.items()
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


def read_grid(data: list[str], map_to_integers: bool = False) -> list[tuple[int, int, int | str]]:
    """
    Extract dimensions and clues from the input data, using 1-based indexing.

    Args:
        data: The input grid as a list of strings
        map_to_integers: If True, map all symbols to unique integers (1-indexed)

    Returns:
        A list of tuples (row, col, value), where value is a string if it's a character,
        or an int if it's a number (or if map_to_integers is True).
    """
    symbol_to_id = {}
    if map_to_integers:
        # First, collect all unique symbols
        unique_symbols = set()
        for row in data:
            for char in row:
                if char != ".":
                    unique_symbols.add(char)

        # Create mapping from symbols to integer IDs
        # First map numbers to themselves (if they exist)
        used_ids = set()

        # Map numeric symbols first
        for symbol in unique_symbols:
            if symbol.isdigit():
                id_num = int(symbol)
                symbol_to_id[symbol] = id_num
                used_ids.add(id_num)

        # Map non-numeric symbols to unused integers
        next_id = 1
        for symbol in sorted(unique_symbols):  # Sort for consistency
            if symbol not in symbol_to_id:
                while next_id in used_ids:
                    next_id += 1
                symbol_to_id[symbol] = next_id
                used_ids.add(next_id)
                next_id += 1

    clues = []
    for r, line in enumerate(data):
        for c, char in enumerate(line):
            if char != ".":
                if map_to_integers:
                    value = symbol_to_id[char]
                else:
                    value = int(char) if char.isdigit() else char
                clues.append((r + 1, c + 1, value))

    return clues
