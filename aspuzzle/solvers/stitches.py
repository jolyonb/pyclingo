from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.solvers.base import Solver
from pyclingo import ANY, Choice, Count, Equals, Predicate, create_variables


class Stitches(Solver):
    solver_name = "Stitches puzzle solver"
    default_config = {"stitch_count": 1}

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data
        assert isinstance(grid, RectangularGrid)

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

        # Parse regions from the input
        puzzle.section("Define regions", segment="Regions")

        # Create Region facts
        for r, c, region_id in grid_data:
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

    def validate_config(self) -> None:
        """Validate the puzzle configuration."""
        # Check if row and column clues exist
        if "row_clues" not in self.config:
            raise ValueError("Missing row_clues in puzzle configuration")
        if "col_clues" not in self.config:
            raise ValueError("Missing col_clues in puzzle configuration")

        # Validate clue lengths match grid dimensions
        assert isinstance(self.grid, RectangularGrid)
        if len(self.config["row_clues"]) != self.grid.rows:
            raise ValueError(f"Expected {self.grid.rows} row clues, got {len(self.config['row_clues'])}")
        if len(self.config["col_clues"]) != self.grid.cols:
            raise ValueError(f"Expected {self.grid.cols} column clues, got {len(self.config['col_clues'])}")

        # Validate that row and column clue sums match
        row_sum = sum(self.config["row_clues"])
        col_sum = sum(self.config["col_clues"])

        if row_sum != col_sum:
            raise ValueError(f"Sum of row clues ({row_sum}) doesn't match sum of column clues ({col_sum})")

        # For Stitches, the sum of clues should be equal to the number of stitches,
        # which is the number of region boundaries times stitch_count * 2.
        # I don't want to do this here though, because it requires a python implementation of finding region boundaries.
