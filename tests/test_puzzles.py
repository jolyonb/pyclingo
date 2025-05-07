import json
from pathlib import Path

import pytest

from aspuzzle.solvers.base import Solver


def get_puzzle_files() -> list[Path]:
    """Find all puzzle JSON files in the puzzles directory."""
    puzzles_dir = Path(__file__).parent.parent / "puzzles"
    return list(puzzles_dir.glob("*.json"))


def test_find_puzzles() -> None:
    """Verify that we can find puzzle files."""
    puzzle_files = get_puzzle_files()
    assert len(puzzle_files) > 0, "No puzzle files found"


@pytest.mark.parametrize("puzzle_file", get_puzzle_files(), ids=lambda p: p.name)
def test_puzzle_solves(puzzle_file: Path) -> None:
    """Test that each puzzle can be solved without errors."""
    with open(puzzle_file) as f:
        config = json.load(f)

    solver = Solver.from_config(config)
    solver.construct_puzzle()
    solutions = solver.solve()

    assert solver.puzzle.satisfiable, f"Puzzle {puzzle_file.name} should be satisfiable"

    # If expected solutions are provided, verify they match
    # TODO: Clean this up to leverage the solver verification?
    if "solutions" in config:
        # Convert found solutions to comparable format
        found_solutions_set = set()
        for sol in solutions:
            solution_set = frozenset(
                (pred_name, frozenset(str(pred) for pred in preds)) for pred_name, preds in sol.items()
            )
            found_solutions_set.add(solution_set)

        # Convert expected solutions to the same format
        expected_solutions_set = set()
        for expected_solution in config["solutions"]:
            solution_set = frozenset((pred_name, frozenset(preds)) for pred_name, preds in expected_solution.items())
            expected_solutions_set.add(solution_set)

        # Check if the sets are equal
        assert found_solutions_set == expected_solutions_set, (
            f"Solutions for {puzzle_file.name} do not match expected solutions"
        )
