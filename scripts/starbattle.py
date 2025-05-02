from pyclingo import (
    ANY,
    Abs,
    ASPProgram,
    Choice,
    Predicate,
    RangePool,
    create_variables,
)

test_data = """aabbb
caaad
cccdd
eeedd
eeeee"""


def parse_regions(data: str) -> tuple[int, list[tuple[int, int, str]]]:
    """Extract grid dimensions and region assignments from input data."""
    lines = data.splitlines()
    size = len(lines)  # Assuming square grid

    # Create a list of (col, row, region_id) tuples
    regions = []
    for r, line in enumerate(lines):
        regions.extend((c, r, region_id) for c, region_id in enumerate(line))
    return size, regions


def main() -> None:
    """Solve a star battle puzzle with the given star count per row/column/region."""
    solver = ASPProgram()

    # Parse the puzzle data
    size, region_data = parse_regions(test_data)
    star_count = 1

    # Register constants
    size = solver.register_symbolic_constant("size", size)
    starcount = solver.register_symbolic_constant("starcount", star_count)

    # Define predicates
    Nums = Predicate.define("nums", ["n"], show=False)
    Region = Predicate.define("region", ["loc", "id"], show=False)
    Star = Predicate.define("star", ["loc"], show=True)
    Cell = Predicate.define("cell", ["row", "col"], show=False)
    Adjacent = Predicate.define("adj", ["cell1", "cell2"], show=False)

    # Create variables
    N, C, R, Radj, Cadj = create_variables("N", "C", "R", "Radj", "Cadj")

    # Add region data as facts
    solver.section("Region Definitions")
    solver.fact(*[Region(Cell(row=r, col=c), region_id) for c, r, region_id in region_data])

    # Define the grid indices
    solver.section("Grid Definition")
    solver.fact(Nums(RangePool(0, size - 1)))
    cell = Cell(row=R, col=C)
    solver.when([Nums(R), Nums(C)], cell)

    # Define adjacent cells
    solver.section("Cell Adjacency")
    cell_adj = Cell(row=Radj, col=Cadj)
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

    # Rule 1: Place starcount stars on each row, column and region
    solver.section("Star Placement Rules")

    # Per row: exactly starcount stars in each row
    solver.when(Nums(R), Choice(Star(cell), condition=Nums(C)).exactly(starcount))

    # Per column: exactly starcount stars in each column
    solver.when(Nums(C), Choice(Star(cell), condition=Nums(R)).exactly(starcount))

    # Per region: exactly starcount stars in each region
    solver.when(Region(loc=ANY, id=N), Choice(Star(cell), condition=Region(cell, N)).exactly(starcount))

    # Rule 2: Stars cannot be touching (including diagonally)
    solver.section("Star Adjacency Constraints")
    solver.forbid(Star(cell), Star(cell_adj), Adjacent(cell, cell_adj))

    # Solve and print the ASP program
    print(solver.render())

    # Solve and display the results
    for result in solver.solve():
        print(result)


if __name__ == "__main__":
    main()
