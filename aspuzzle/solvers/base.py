import pprint
from typing import Any

from aspuzzle.grid import Grid
from aspuzzle.puzzle import Puzzle


class Solver:

    default_config: dict[str, Any] = {}
    solver_name: str = "Puzzle solver"

    def __init__(self, puzzle: Puzzle, grid: Grid, config: dict[str, Any]) -> None:
        self.puzzle = puzzle
        self.puzzle.name = self.solver_name
        self.grid = grid
        # Merge default config with instance config
        self.config = {**self.default_config, **config}

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

        # Print solutions
        for solution in self.puzzle.solve():
            print(solution)

        # Print statistics
        print()
        if self.puzzle.solution_count == 1:
            print("1 solution")
        else:
            print(f"{self.puzzle.solution_count} solutions")
        pprint.pprint(self.puzzle.statistics)

        if "solutions" in self.config:
            # Make sure that the given solutions match the solutions found
            # TODO
            pass
