from aspuzzle.grid import Grid
from aspuzzle.puzzle import Puzzle
from aspuzzle.symbolset import SymbolSet, set_count_constraint
from pyclingo import (
    ANY,
    Count,
    Equals,
    Predicate,
    create_variables,
)
from scripts.utils import read_grid


def solve_minesweeper(data: str, num_mines: int | None = None):
    """
    Solve a Minesweeper puzzle from the given string data.

    Args:
        data: String representation of the puzzle
        num_mines: Number of mines to place

    Returns:
        A generator yielding solutions
    """
    # Parse the puzzle data
    rows, cols, clues = read_grid(data)

    # Create the puzzle
    puzzle = Puzzle("Minesweeper puzzle solver")
    grid = Grid(puzzle, rows, cols)

    # Define predicates
    Number = Predicate.define("number", ["loc", "num"], show=False)

    # Create variables
    N, Minecount = create_variables("N", "Minecount")
    cell = grid.cell()
    cell_adj = grid.cell(suffix="adj")

    # Define mine placement
    symbols = SymbolSet(grid).add_symbol("mine").excluded_symbol(Number(loc=cell, num=ANY))

    # Number constraints: each number indicates exactly how many mines are adjacent
    puzzle.section("Numbers indicate the number of adjacent mines")
    surrounding_count = Count(
        cell_adj,
        condition=[
            grid.VertexSharing(cell1=cell, cell2=cell_adj),
            symbols["mine"](loc=cell_adj),
        ],
    ).assign_to(Minecount)
    puzzle.when([Number(loc=cell, num=N), surrounding_count], let=Equals(N, Minecount))

    # Impose mine count constraint
    if num_mines:
        puzzle.section("Mine count constraint")
        set_count_constraint(grid, symbols["mine"](loc=grid.cell()), exactly=num_mines)

    # Add clues as facts
    puzzle.blank_line(segment="Clues")
    puzzle.fact(
        *[Number(loc=grid.Cell(row=r, col=c), num=num) for r, c, num in clues],
        segment="Clues",
    )

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

    solve_minesweeper(test_data, 7)


if __name__ == "__main__":
    main()
