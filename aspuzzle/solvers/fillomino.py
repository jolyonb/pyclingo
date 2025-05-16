from typing import Any

from aspuzzle.grids.rendering import BgColor, Color, RenderItem
from aspuzzle.regionconstructor import RegionConstructor
from aspuzzle.solvers.base import Solver
from pyclingo import Not, Predicate, create_variables


class Fillomino(Solver):
    solver_name = "Fillomino puzzle solver"
    supported_symbols = list(range(1, 30)) + ["."]  # Support numbers + empty cells

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Define predicates
        Clue = Predicate.define("clue", ["loc", "size"], show=False)
        Number = Predicate.define("number", ["loc", "size"], show=True)

        # Define clues from the input grid
        puzzle.fact(
            *[Clue(loc=grid.Cell(*loc), size=size) for loc, size in grid_data],
            segment="Clues",
        )

        # Create variables for convenience
        A, C, C_adj, C2, N, S, S2, A1, A2 = create_variables("A", "C", "C_adj", "C2", "N", "S", "S2", "A1", "A2")

        # Create the region constructor to construct polyominoes
        region_constructor = RegionConstructor(
            puzzle=puzzle,
            grid=grid,
            anchor_predicate=None,
            allow_regionless=False,
        )

        # Rule 1: Fill each cell with a number corresponding to the size of its region
        puzzle.section("Region size determines the number in each cell")
        puzzle.when(
            [
                region_constructor.Region(loc=C, anchor=A),
                region_constructor.RegionSize(anchor=A, size=S),
            ],
            Number(loc=C, size=S),
        )

        # Rule 2: Ensure that given clues match the numbers obtained from region sizes
        puzzle.section("Given clues must match their region sizes")
        puzzle.when(
            [
                Clue(loc=C, size=S),
                Number(loc=C, size=N),
            ],
            let=(N == S),
        )

        # Rule 3: Ensure that adjacent regions have different sizes
        puzzle.section("Regions with same size cannot touch orthogonally")
        # Splitting off the separate predicate here is important for performance!
        DifferentRegions = Predicate.define("different_regions", ["cell1", "cell2"], show=False)
        puzzle.when(
            [
                grid.Orthogonal(cell1=C, cell2=C_adj),
                region_constructor.Region(loc=C, anchor=A),
                Not(region_constructor.Region(loc=C_adj, anchor=A)),
            ],
            let=DifferentRegions(cell1=C, cell2=C_adj),
        )
        puzzle.forbid(DifferentRegions(C, C_adj), Number(C, N), Number(C_adj, N))

        # Solver helpers
        if any(size == 1 for _, size in grid_data):
            puzzle.section("1 clues must be anchors")
            puzzle.when(Clue(loc=C, size=1), let=region_constructor.Anchor(loc=C))

        puzzle.section("Adjacent clues with the same value must be in the same region")
        puzzle.when(
            [Clue(loc=C, size=S), Clue(loc=C_adj, size=S), grid.Orthogonal(cell1=C, cell2=C_adj)],
            let=region_constructor.ConnectsTo(loc1=C, loc2=C_adj),
        )

        puzzle.section("Adjacent clues with different values must be in different regions")
        puzzle.forbid(
            Clue(loc=C, size=S),
            Clue(loc=C_adj, size=S2),
            S != S2,
            grid.Orthogonal(cell1=C, cell2=C_adj),
            region_constructor.ConnectsTo(loc1=C, loc2=C_adj),
        )

        # These rules did not help the solver

        # puzzle.section("Size-1 regions cannot connect to other cells")
        # puzzle.forbid(Clue(loc=C, size=1), region_constructor.ConnectsTo(loc1=C, loc2=ANY))

        # puzzle.section("Clues with different numbers cannot have the same anchor")
        # puzzle.forbid(
        #     Clue(loc=C, size=S),
        #     Clue(loc=C2, size=S2),
        #     region_constructor.Region(loc=C, anchor=A),
        #     region_constructor.Region(loc=C2, anchor=A),
        #     S != S2,
        # )

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Fillomino solver.

        Returns:
            Dictionary with rendering configuration for Fillomino
        """
        # Basic colors for the numbers
        colors = [
            Color.BLUE,  # 1
            Color.GREEN,  # 2
            Color.RED,  # 3
            Color.MAGENTA,  # 4
            Color.CYAN,  # 5
            Color.YELLOW,  # 6
            Color.BRIGHT_BLUE,  # 7
            Color.BRIGHT_GREEN,  # 8
            Color.BRIGHT_RED,  # 9
        ]

        # Define backgrounds for each region size
        backgrounds = [
            None,  # 1 (no background)
            BgColor.BRIGHT_BLACK,  # 2
            BgColor.BLUE,  # 3
            BgColor.GREEN,  # 4
            BgColor.RED,  # 5
            BgColor.MAGENTA,  # 6
            BgColor.CYAN,  # 7
            BgColor.YELLOW,  # 8
            BgColor.WHITE,  # 9
        ]

        # Map initial clues to symbols with appropriate colors
        puzzle_symbols = {i: {"symbol": str(i) if i > 10 else "#", "color": colors[(i - 1) % 9]} for i in range(1, 30)}

        # Setup predicates for rendering
        # The actual number will be shown with the appropriate color
        # The background will help visually identify different regions
        predicates = {
            "number": {
                "value": "size",
                "color": None,  # Will use color from puzzle_symbols
                "custom_renderer": lambda pred: [
                    RenderItem(
                        loc=pred["loc"],
                        symbol=str(pred["size"].value),
                        color=colors[pred["size"].value - 1] if 1 <= pred["size"].value <= 9 else Color.WHITE,
                        background=backgrounds[pred["size"].value - 1] if 1 <= pred["size"].value <= 9 else None,
                    )
                ],
            }
        }

        return {
            "puzzle_symbols": puzzle_symbols,
            "predicates": predicates,
            "join_char": "",  # No space between cells
        }
