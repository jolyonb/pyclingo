import importlib
import json
import pathlib

from aspuzzle.puzzle import Puzzle
from aspuzzle.solvers.base import Solver


def solve(filename: str) -> None:
    """
    Loads the puzzle from the given filename and solves it.
    """
    # Find the file to open
    if not filename.endswith(".json"):
        filename += ".json"
    path = pathlib.Path(filename)

    if not path.exists():
        # Try in examples directory
        path = path.parent / "examples" / filename

    with open(path) as f:
        config = json.load(f)

    # Create a puzzle object
    puzzle = Puzzle()

    # Load the appropriate solver
    module = importlib.import_module(f"aspuzzle.solvers.{config['puzzle_type'].lower()}")
    puzzle_class: type[Solver] = getattr(module, config["puzzle_type"])

    # Construct the puzzle rules
    solver = puzzle_class(puzzle=puzzle, config=config)

    # Create a grid object
    solver.create_grid()

    # Validate the config
    solver.validate()

    solver.construct_puzzle()

    # Solve the puzzle
    solver.solve()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("filename")
    args = parser.parse_args()
    solve(args.filename)
