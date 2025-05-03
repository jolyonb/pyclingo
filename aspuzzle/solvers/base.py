import pprint
from typing import Any

from aspuzzle.grid import Grid
from aspuzzle.puzzle import Puzzle


class Solver:

    def __init__(self, puzzle: Puzzle, grid: Grid, config: dict[str, Any]) -> None:
        self.puzzle = puzzle
        self.grid = grid
        self.config = config

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
