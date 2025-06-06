from typing import Any

from aspuzzle.grids.rendering import BgColor, Color, RenderSymbol
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import Predicate, create_variables


class Hitori(Solver):
    solver_name = "Hitori puzzle solver"
    supported_symbols = list(range(1, 10))  # Support digits 1-9 as symbols

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Define the predicate for the number in a cell
        Value = Predicate.define("value", ["loc", "num"], show=False)

        # Variables for use
        D, N, Idx, C1, C2 = create_variables("D", "N", "Idx", "C1", "C2")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define grid values from the input grid
        puzzle.section("Define grid values")
        puzzle.fact(
            *[Value(loc=grid.Cell(*loc), num=v) for loc, v in grid_data],
            segment="Clues",
        )

        # Define shaded/unshaded cells using a symbol set
        symbols = SymbolSet(grid, fill_all_squares=True).add_symbol("black").add_symbol("white")

        # Rule 1: No number should appear unshaded more than once in a line
        puzzle.section("Rule 1: No duplicated unshaded numbers in a line")
        puzzle.when(
            conditions=[
                grid.Line(direction=D, index=Idx, loc=C1),
                grid.Line(direction=D, index=Idx, loc=C2),
                Value(loc=C1, num=N),
                Value(loc=C2, num=N),
                symbols["white"](loc=C1),
                symbols["white"](loc=C2),
            ],
            let=(C1 == C2),
        )

        # Rule 2: Two black cells cannot be adjacent horizontally or vertically
        puzzle.section("Rule 2: No adjacent black cells")
        puzzle.forbid(
            symbols["black"](loc=cell),
            symbols["black"](loc=cell_adj),
            grid.Orthogonal(cell1=cell, cell2=cell_adj),
        )

        # Rule 3: All white cells should be connected
        puzzle.section("Rule 3: All white cells must be connected")
        symbols.make_contiguous("white")

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Hitori solver.

        Returns:
            Dictionary with rendering configuration for Hitori
        """
        return {
            "puzzle_symbols": {
                1: RenderSymbol("1", Color.BLUE),
                2: RenderSymbol("2", Color.BLUE),
                3: RenderSymbol("3", Color.BLUE),
                4: RenderSymbol("4", Color.BLUE),
                5: RenderSymbol("5", Color.BLUE),
                6: RenderSymbol("6", Color.BLUE),
                7: RenderSymbol("7", Color.BLUE),
                8: RenderSymbol("8", Color.BLUE),
                9: RenderSymbol("9", Color.BLUE),
            },
            "predicates": {
                "black": {"symbol": None, "background": BgColor.WHITE},
                "white": {"symbol": None, "background": None},
            },
            "join_char": "",
        }
