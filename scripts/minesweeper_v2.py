from aspuzzle.grid import Grid
from aspuzzle.puzzle import Puzzle
from pyclingo import ANY, Choice, Predicate, Variable


def unpack_data(data: str) -> tuple[int, int, list[tuple[int, int, int]]]:
    """Extract dimensions and number clues from the input data."""
    data = data.strip()
    lines = data.splitlines()
    rows = len(lines)
    cols = len(lines[0])
    clues = []

    for r, line in enumerate(lines):
        clues.extend((r, c, int(char)) for c, char in enumerate(line) if char.isdigit())
    return rows, cols, clues


def solve_minesweeper(data: str):
    """
    Solve a Minesweeper puzzle from the given string data.

    Args:
        data: String representation of the puzzle

    Returns:
        A generator yielding solutions
    """
    # Parse the puzzle data
    rows, cols, clues = unpack_data(data)

    # Create the puzzle and grid module
    puzzle = Puzzle("Minesweeper")

    r = puzzle.register_symbolic_constant("r", rows)
    c = puzzle.register_symbolic_constant("c", cols)

    grid = Grid(puzzle, r, c)

    # Define Minesweeper-specific predicates in the default segment
    Number = Predicate.define("number", ["loc", "num"], show=False)
    Mine = Predicate.define("mine", ["loc"], show=True)

    # Add clues as facts
    puzzle.section("Clues")
    for r, c, num in clues:
        puzzle.fact(Number(loc=grid.Cell(row=r, col=c), num=num))

    # Create variables for rules
    N = Variable("N")
    cell = grid.cell()
    cell_adj = grid.cell(suffix="adj")

    # Define possible mine locations
    puzzle.section("Mine Placement Rules")
    puzzle.when(cell, Choice(Mine(loc=cell)))

    # Numbers can't have mines
    puzzle.forbid(Number(loc=cell, num=ANY), Mine(loc=cell))

    # Number constraints: each number indicates exactly how many mines are adjacent
    puzzle.section("Number Constraints")
    puzzle.when(
        Number(loc=cell, num=N),
        Choice(
            Mine(loc=cell_adj), condition=grid.Adjacent(cell1=cell, cell2=cell_adj)
        ).exactly(N),
    )

    print(puzzle.render())

    for solution in puzzle.solve():
        print(solution)

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
