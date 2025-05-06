import argparse
import importlib
import json
import pathlib

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
        # Try looking in the puzzles directory
        path = path.parent / "puzzles" / filename

    with open(path) as f:
        config = json.load(f)

    # Load the appropriate solver
    module = importlib.import_module(f"aspuzzle.solvers.{config['puzzle_type'].lower()}")
    puzzle_class: type[Solver] = getattr(module, config["puzzle_type"])

    # Initialize the puzzle class
    solver = puzzle_class(config)

    # Construct the puzzle rules
    solver.construct_puzzle()

    # Solve the puzzle
    solver.solve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("filename")
    args = parser.parse_args()
    solve(args.filename)
