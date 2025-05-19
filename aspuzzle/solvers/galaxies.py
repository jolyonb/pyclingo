from typing import Any

from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.grids.rendering import BgColor, Color, RenderItem
from aspuzzle.regionconstructor import RegionConstructor
from aspuzzle.solvers.base import Solver
from pyclingo import ANY, Not, Predicate, create_variables


class Galaxies(Solver):
    """
    This is a galaxies solver on a rectangular grid.

    Because the point symmetry rule is intrinsically tied to the geometry of the grid, we will implement separate
    solvers for different grid geometries.
    """

    solver_name = "Spiral Galaxies solver"
    supported_grid_types = (RectangularGrid,)

    def process_data(self) -> dict[str | int, list[tuple[int, ...]]]:
        """Process grid data to organize by symbol type"""
        symbols_dict: dict[str | int, list[tuple[int, ...]]] = {}
        for loc, symbol in self.grid_data:
            if symbol not in symbols_dict:
                symbols_dict[symbol] = []
            symbols_dict[symbol].append(loc)
        return symbols_dict

    def validate_config(self) -> None:
        """Validate the puzzle configuration."""
        symbols_dict = self.process_data()

        for e in symbols_dict:
            if len(symbols_dict[e]) not in (1, 2):
                raise ValueError(f"Each symbol must occur either once or twice in the grid. Problem with {e}.")
            if len(symbols_dict[e]) == 2:
                # Ensure that symbols are close to each other
                loc1, loc2 = symbols_dict[e]
                if abs(loc1[0] - loc2[0]) > 1 or abs(loc1[1] - loc2[1]) > 1:
                    raise ValueError(f"Symbols must be close to each other. Problem with {e}: {loc1}, {loc2}.")

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()
        assert isinstance(grid, RectangularGrid)

        symbols_dict = self.process_data()

        # Define predicates
        Center = Predicate.define("center", ["loc", "loc2", "id"], show=False)

        # Define clues - the clues contain cells on either side of the center
        for region_id, locations in enumerate(symbols_dict.values(), start=1):
            loc1 = grid.Cell(*locations[0])
            loc2 = loc1 if len(locations) == 1 else grid.Cell(*locations[1])
            puzzle.fact(Center(loc=loc1, loc2=loc2, id=region_id), segment="Clues")

        # Divide the grid into regions using the first cell in each clue as an anchor
        region_constructor = RegionConstructor(
            puzzle=puzzle,
            grid=grid,
            anchor_predicate=Center,
            anchor_fields={"loc2": ANY, "id": ANY},
            allow_regionless=False,
        )

        # Impose the symmetry constraint
        puzzle.section("Symmetry rule")
        R, C, R1, C1, R2, C2, Id = create_variables("R", "C", "R1", "C1", "R2", "C2", "Id")
        puzzle.forbid(
            Center(loc=grid.Cell(R1, C1), loc2=grid.Cell(R2, C2), id=Id),
            region_constructor.Region(loc=grid.Cell(R, C), anchor=grid.Cell(R1, C1)),
            Not(region_constructor.Region(loc=grid.Cell(R1 + R2 - R, C1 + C2 - C), anchor=grid.Cell(R1, C1))),
        )

        # Define a predicate to extract the regions from the puzzle for solution display purposes
        puzzle.section("Solution extraction")
        Galaxy = Predicate.define("galaxy", ["loc", "id"], show=True)
        Loc, A, Id = create_variables("Loc", "A", "Id")
        puzzle.when(
            [
                region_constructor.Region(loc=Loc, anchor=A),
                Center(loc=A, loc2=ANY, id=Id),
            ],
            let=Galaxy(loc=Loc, id=Id),
        )

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Galaxies solver.

        Returns:
            Dictionary with rendering configuration for Galaxies
        """
        # Create an array of distinct background colors to cycle through for different regions
        region_colors = [
            BgColor.BRIGHT_BLACK,
            BgColor.BLUE,
            BgColor.GREEN,
            BgColor.RED,
            BgColor.MAGENTA,
            BgColor.CYAN,
            BgColor.YELLOW,
            BgColor.BRIGHT_BLUE,
            BgColor.BRIGHT_GREEN,
            BgColor.BRIGHT_RED,
            BgColor.BRIGHT_MAGENTA,
            BgColor.BRIGHT_CYAN,
            BgColor.BRIGHT_YELLOW,
        ]

        # Create a closure to track the color index
        color_index = [0]

        def region_renderer(pred: Predicate) -> list[RenderItem]:
            """
            Custom renderer for regions that assigns unique colors based on region ID.
            Colors cycle through the available palette.
            """
            region_id = pred["id"].value

            # Use region_id to determine color, if we haven't seen this region before
            if region_id >= len(color_index):
                # Add new colors as needed
                while len(color_index) <= region_id:
                    color_index.append(color_index[0] % len(region_colors))
                    color_index[0] += 1

            # Get the background color for this region
            background = region_colors[color_index[region_id]]

            # Create a render item with the background color
            return [
                RenderItem(
                    loc=pred["loc"],
                    symbol=None,
                    background=background,
                )
            ]

        # For the puzzle symbols, show dots for empty cells and circles for centers
        return {
            "puzzle_symbols": {
                ".": {"symbol": ".", "color": Color.WHITE},  # Dot for empty cells
            },
            "predicates": {
                "galaxy": {"custom_renderer": region_renderer},
            },
            "join_char": "",  # No space between cells
        }
