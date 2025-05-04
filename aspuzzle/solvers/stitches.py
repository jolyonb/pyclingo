from aspuzzle.solvers.base import Solver
from aspuzzle.utils import read_grid
from pyclingo import ANY, Choice, Count, Equals, Predicate, create_variables


class Stitches(Solver):
    solver_name = "Stitches puzzle solver"
    default_config = {
        "stitch_count": 1,
    }

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config = self.pgc

        # Register stitch count as a symbolic constant
        stitch_count = puzzle.register_symbolic_constant("stitch_count", config["stitch_count"])

        # Define predicates
        Region = Predicate.define("region", ["loc", "id"], show=False)
        AdjoiningRegion = Predicate.define("adjoining_region", ["id1", "id2"], show=False)
        Stitch = Predicate.define("stitch", ["loc1", "loc2"], show=True)
        ExpectedCounts = Predicate.define("expected_count", ["dir", "index", "count"], show=False)
        CellInStitch = Predicate.define("cell_in_stitch", ["loc"], show=False)

        # Create variables
        Dir, Counter, N, A, B = create_variables("Dir", "Counter", "N", "A", "B")
        Id1, Id2 = create_variables("Id1", "Id2")
        cell = grid.cell()
        cell1 = grid.cell(suffix="1")
        cell2 = grid.cell(suffix="2")

        # Parse regions from the input
        puzzle.section("Define regions", segment="Regions")
        region_data = read_grid(config["regions"], map_to_integers=True)

        # Create Region facts
        for r, c, region_id in region_data:
            puzzle.fact(Region(loc=grid.Cell(row=r, col=c), id=region_id), segment="Regions")

        # Define expected row and column counts
        puzzle.section("Stitch counts", segment="Clues")
        # Row counts (direction 'e' for rows)
        for i, count in enumerate(config["row_clues"], 1):
            puzzle.fact(ExpectedCounts(dir="e", index=i, count=count), segment="Clues")
        # Column counts (direction 's' for columns)
        for i, count in enumerate(config["col_clues"], 1):
            puzzle.fact(ExpectedCounts(dir="s", index=i, count=count), segment="Clues")

        # Rule 1: Identify adjoining regions (with Id1 < Id2)
        puzzle.section("Find adjoining regions")
        puzzle.when(
            [
                Region(loc=A, id=Id1),
                Region(loc=B, id=Id2),
                grid.Orthogonal(A, B),
                Id1 < Id2,  # Ensure we don't duplicate pairs
            ],
            let=AdjoiningRegion(id1=Id1, id2=Id2),
        )

        # Rule 2: For each adjoining region pair, create exactly stitch_count stitches
        puzzle.section("Create stitches between adjoining regions")
        puzzle.when(
            AdjoiningRegion(id1=Id1, id2=Id2),
            let=Choice(
                element=Stitch(loc1=A, loc2=B),
                condition=[
                    Region(loc=A, id=Id1),
                    Region(loc=B, id=Id2),
                    grid.Orthogonal(A, B),
                ],
            ).exactly(stitch_count),
        )

        puzzle.section("Define cells in stitches")
        puzzle.when(Stitch(loc1=A, loc2=ANY), let=CellInStitch(loc=A))
        puzzle.when(Stitch(loc1=ANY, loc2=A), let=CellInStitch(loc=A))

        # Rule 3: Each cell can participate in at most one stitch
        puzzle.section("Cells can participate in at most one stitch")
        # For each cell that is in a stitch, count the number of other cells
        # that it is connected to via a stitch. We enforce that this must be one.
        count_expr = Count(element=cell, condition=Stitch(loc1=A, loc2=cell)).add(
            element=cell, condition=Stitch(loc1=cell, loc2=A)
        )
        puzzle.when([CellInStitch(loc=A), count_expr.assign_to(N)], let=Equals(N, 1))

        # Rule 4: Count stitches per line (row/column/etc)
        puzzle.section("Count stitches in each major line")
        puzzle.count_constraint(
            count_over=cell,
            condition=[CellInStitch(loc=cell), grid.Line(direction=Dir, index=N, loc=cell)],
            when=ExpectedCounts(dir=Dir, index=N, count=Counter),
            exactly=Counter,
        )
