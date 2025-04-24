from pyclingo.choice import Choice
from pyclingo.expression import Abs
from pyclingo.pool import RangePool
from pyclingo.predicate import Predicate
from pyclingo.solver import ASPProgram
from pyclingo.value import Variable

test_data = """.2...
..32.
3..2.
.2..1
..12."""


def unpack_data(data: str) -> tuple[int, int, list[tuple[int, int, int]]]:
    """Extract dimensions and number clues from the input data."""
    lines = data.splitlines()
    rows = len(lines)
    cols = len(lines[0])
    clues = []

    for r, line in enumerate(lines):
        clues.extend(
            (r, c, int(char)) for c, char in enumerate(line) if char.isdigit()
        )
    return rows, cols, clues


def main() -> None:
    solver = ASPProgram()

    # Parse the puzzle data
    row_count, col_count, clues = unpack_data(test_data)

    # Register constants for grid dimensions
    r = solver.register_symbolic_constant("r", row_count)
    c = solver.register_symbolic_constant("c", col_count)

    # Define predicates
    Cell = Predicate.define("cell", ["row", "col"], show=False)
    Number = Predicate.define("number", ["row", "col", "num"], show=False)
    Mine = Predicate.define("mine", ["row", "col"], show=True)
    Adjacent = Predicate.define("adj", ["cell1", "cell2"], show=False)

    # Add clues as facts
    solver.section("Clues")
    solver.fact(*[Number(r0, c0, num0) for r0, c0, num0 in clues])

    # Create variables
    R = Variable("R")
    C = Variable("C")
    Radj = Variable("Radj")
    Cadj = Variable("Cadj")
    N = Variable("N")
    # Useful aliases
    cell = Cell(row=R, col=C)
    cell_adj = Cell(row=Radj, col=Cadj)

    # Create all cells in the grid
    solver.section("Grid Definition")
    solver.when([R.in_(RangePool(0, r - 1)), C.in_(RangePool(0, c - 1))], cell)

    # Define possible mine locations (any cell without a number)
    solver.section("Mine Placement Rules")
    solver.when(cell, Choice(Mine(R, C)))
    solver.forbid(Number(R, C, N), Mine(R, C))

    # Define adjacent cells
    solver.section("Cell Adjacency")
    solver.when(
        [
            cell,
            cell_adj,
            Abs(R - Radj) <= 1,
            Abs(C - Cadj) <= 1,
            Abs(R - Radj) + Abs(C - Cadj) > 0,  # Not the same cell
        ],
        Adjacent(cell, cell_adj),
    )

    # Number constraints: each number indicates exactly how many mines are adjacent
    solver.section("Number Constraints")
    solver.when(
        Number(R, C, N),
        Choice(Mine(Radj, Cadj), condition=Adjacent(cell, cell_adj)).exactly(N),
    )

    print(solver.render())


if __name__ == "__main__":
    main()
