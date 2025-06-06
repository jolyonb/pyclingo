from typing import Any

from aspuzzle.grids.region_coloring import assign_region_colors
from aspuzzle.grids.rendering import BgColor, Color, RenderItem, RenderSymbol
from aspuzzle.solvers.base import Solver
from pyclingo import ANY, Choice, Count, Predicate, create_variables


class Stitches(Solver):
    solver_name = "Stitches puzzle solver"
    default_config = {"stitch_count": 1}
    map_grid_to_integers = True
    _region_colors: dict[Any, BgColor]

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

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
        puzzle.fact(
            *[Region(loc=grid.Cell(*loc), id=region_id) for loc, region_id in grid_data],
            segment="Regions",
        )

        # Define expected line counts
        puzzle.section("Stitch counts", segment="Clues")
        for direction in grid.line_direction_names:
            clue_key = f"{grid.line_direction_descriptions[direction]}_clues"
            for i, count in enumerate(config[clue_key], 1):
                if count is not None:
                    puzzle.fact(ExpectedCounts(dir=direction, index=i, count=count), segment="Clues")

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
        count_expr = N == Count(element=cell, condition=Stitch(loc1=A, loc2=cell)).add(
            element=cell, condition=Stitch(loc1=cell, loc2=A)
        )
        puzzle.when([CellInStitch(loc=A), count_expr], let=(N == 1))

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
        self.validate_line_clues()

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Stitches solver.

        Returns:
            Dictionary with rendering configuration for Stitches
        """
        # Create an array of distinct colors to cycle through
        stitch_colors = [
            Color.BRIGHT_MAGENTA,
            Color.BRIGHT_CYAN,
            Color.BRIGHT_YELLOW,
            Color.BRIGHT_GREEN,
        ]

        # Create a closure to track the color index
        color_index = [0]

        def stitch_renderer(pred: Predicate) -> list[RenderItem]:
            # Get the next color and increment the index
            color = stitch_colors[color_index[0] % len(stitch_colors)]
            color_index[0] += 1

            # Return both ends of the stitch with the same color
            return [
                RenderItem(loc=pred["loc1"], symbol="X", color=color),
                RenderItem(loc=pred["loc2"], symbol="X", color=color),
            ]

        puzzle_symbols = {}
        for region_id, background_color in self._region_colors.items():
            puzzle_symbols[region_id] = RenderSymbol(".", bgcolor=background_color)

        return {
            "puzzle_symbols": puzzle_symbols,
            "predicates": {
                "stitch": {"custom_renderer": stitch_renderer},
            },
            "join_char": "",
        }

    def _preprocess_config(self) -> None:
        """Precompute region colors for rendering."""
        regions: dict[Any, list[tuple[int, ...]]] = {}
        for loc, region_id in self.grid_data:
            regions.setdefault(region_id, []).append(loc)

        self._region_colors = assign_region_colors(self.grid, regions)
