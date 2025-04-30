from aspuzzle.grid import Grid
from aspuzzle.puzzle import Puzzle
from pyclingo import (
    ANY,
    Choice,
    Predicate,
    Variable,
    Not,
    NotEquals,
    Count,
)
from scripts.utils import read_grid

def solve_minesweeper(data: str):
    """
    Solve a Minesweeper puzzle from the given string data.

    Args:
        data: String representation of the puzzle

    Returns:
        A generator yielding solutions
    """
    # Parse the puzzle data
    rows, cols, clues = read_grid(data)

    # Create the puzzle
    puzzle = Puzzle("Minesweeper puzzle solver")
    grid = Grid(puzzle, rows, cols, primary_namespace=True)

    # Define predicates
    Number = Predicate.define("number", ["loc", "num"], show=False)
    Mine = Predicate.define("mine", ["loc"], show=True)

    # Create variables
    N = Variable("N")
    cell = grid.cell()
    cell_adj = grid.cell(suffix="adj")

    # Define possible mine locations
    puzzle.section("Any cell without a number can have a mine")
    puzzle.when(conditions=[cell, Not(Number(loc=cell, num=ANY))], let=Choice(Mine(loc=cell)))

    # Number constraints: each number indicates exactly how many mines are adjacent
    puzzle.section("Numbers indicate the number of adjacent mines")
    puzzle.forbid(
        Number(loc=cell, num=N),
        NotEquals(
            Count(
                cell_adj,
                condition=[grid.VertexSharing(cell1=cell, cell2=cell_adj), Mine(loc=cell_adj)],
            ),
            N,
        ),
    )

    # Add clues as facts
    puzzle.section("Clues")
    puzzle.fact(*[Number(loc=grid.Cell(row=r, col=c), num=num) for r, c, num in clues])

    print(puzzle.render())

    for solution in puzzle.solve():
        print(solution)

    print()
    print(f"{puzzle.solution_count} solutions")
    print(puzzle.statistics)


def main():
    test_data = """
.2...
..32.
3..2.
.2..1
..12.
"""

    solve_minesweeper(test_data)


if __name__ == "__main__":
    main()
