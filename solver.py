import argparse
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

    # Create the appropriate solver
    solver = Solver.from_config(config)

    # Construct the puzzle rules
    solver.construct_puzzle()

    # Render the puzzle
    print(solver.puzzle.render())

    # Solve the puzzle
    solutions = solver.solve()

    # Display solutions
    solver.display_results(solutions)

    # Print statistics
    solver.display_statistics()

    # Validate solutions
    solver.validate_solutions(solutions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("filename")
    args = parser.parse_args()
    solve(args.filename)
