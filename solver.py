import importlib
import json

from aspuzzle.grid import Grid
from aspuzzle.puzzle import Puzzle
from aspuzzle.solvers.base import Solver


def solve(filename: str) -> None:
    """
    Loads the puzzle from the given filename and solves it.
    """
    with open(filename) as f:
        config = json.load(f)

    # Create a puzzle object
    puzzle = Puzzle()

    # Create a grid object from the config
    if config["grid_type"] == "RectangularGrid":
        grid = Grid(puzzle, **config["grid_params"])
    else:
        raise ValueError(f"Unknown grid type {config['grid_type']}")

    # Load the appropriate solver
    module = importlib.import_module(f"aspuzzle.solvers.{config['puzzle_type'].lower()}")
    puzzle_class: type[Solver] = getattr(module, config["puzzle_type"])

    # Construct the puzzle rules
    solver = puzzle_class(grid=grid, puzzle=puzzle, config=config)
    solver.construct_puzzle()

    # Solve the puzzle
    solver.solve()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("filename")
    args = parser.parse_args()
    solve(args.filename)
