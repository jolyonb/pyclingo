from typing import Any

from aspuzzle.grids.rendering import BgColor, Color
from aspuzzle.regionconstructor import RegionConstructor
from aspuzzle.solvers.base import Solver
from pyclingo import ANY, Predicate, create_variables


class Nurikabe(Solver):
    solver_name = "Nurikabe puzzle solver"
    supported_symbols = ["."] + list(range(1, 100))  # Support numbers 1-99 as island sizes

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Define predicates
        Clue = Predicate.define("clue", ["loc", "size"], show=False)

        # Define island clues from the input grid
        puzzle.section("Define numbered islands", segment="Clues")
        puzzle.fact(
            *[Clue(loc=grid.Cell(*loc), size=size) for loc, size in grid_data],
            segment="Clues",
        )

        # Create the region constructor for islands, anchored on the clues
        # This handles a LOT of the rules!
        region_constructor = RegionConstructor(
            puzzle=puzzle,
            grid=grid,
            anchor_predicate=Clue,  # Clue cells are anchors for islands
            anchor_fields={"size": ANY},
            allow_regionless=True,  # Regionless cells form the stream
            forbid_regionless_pools=True,  # No 2x2 pools of stream
            contiguous_regionless=True,  # Stream must be contiguous
            non_adjacent_regions=True,  # Each island must be isolated
        )

        puzzle.section("Each island must have the correct size")
        C, C_adj, N, Size = create_variables("C", "C_adj", "N", "Size")
        puzzle.when(
            [
                Clue(loc=C, size=N),
                region_constructor.RegionSize(anchor=C, size=Size),
            ],
            N == Size,
        )

        if any(size == 1 for loc, size in grid_data):
            puzzle.section("Size-1 islands must be fully surrounded by stream")
            puzzle.when(
                [Clue(loc=C, size=1), grid.Orthogonal(cell1=C, cell2=C_adj)], region_constructor.Regionless(loc=C_adj)
            )

        puzzle.section("Solution readout")
        Stream = Predicate.define("stream", ["loc"], show=True)
        Island = Predicate.define("island", ["loc"], show=True)
        puzzle.when(region_constructor.Regionless(loc=C), Stream(loc=C))
        puzzle.when(region_constructor.Region(loc=C, anchor=ANY), Island(loc=C))

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Nurikabe solver.

        Returns:
            Dictionary with rendering configuration for Nurikabe
        """
        # For clue numbers, use the digits as is
        puzzle_symbols = {i: {"symbol": str(i), "color": Color.BRIGHT_BLUE} for i in range(1, 100)}

        return {
            "puzzle_symbols": puzzle_symbols,
            "predicates": {
                "stream": {"symbol": None, "background": BgColor.BRIGHT_BLACK},
                "island": {"symbol": None, "background": None},
            },
            "join_char": "",
        }
