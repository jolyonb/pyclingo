from typing import Any

from aspuzzle.grids.base import do_not_show_outside
from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.grids.rendering import BgColor, Color, RenderSymbol
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import Not, Predicate, create_variables


class Slitherlink(Solver):
    solver_name = "Slitherlink puzzle solver"
    supported_symbols = list(range(4)) + [".", "S", "W"]

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Define predicates
        Clue = Predicate.define("clue", ["loc", "num"], show=False)
        Sheep = Predicate.define("sheep", ["loc"], show=False)
        Wolf = Predicate.define("wolf", ["loc"], show=False)

        # Create variables
        N, C, C_adj = create_variables("N", "C", "C_adj")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define clues
        puzzle.section("Grid data", segment="Clues")
        puzzle.fact(
            *[Clue(loc=grid.Cell(*loc), num=v) for loc, v in grid_data if v in (0, 1, 2, 3)],
            segment="Clues",
        )

        # Define sheep
        sheep_facts = [Sheep(loc=grid.Cell(*loc)) for loc, v in grid_data if v == "S"]
        if sheep_facts:
            puzzle.fact(*sheep_facts, segment="Clues")

        # Define wolves
        wolf_facts = [Wolf(loc=grid.Cell(*loc)) for loc, v in grid_data if v == "W"]
        if wolf_facts:
            puzzle.fact(*wolf_facts, segment="Clues")

        # Define inside/outside regions
        symbols = SymbolSet(grid, fill_all_squares=True).add_symbol("inside").add_symbol("outside")

        # Rule 1: All outside border cells are outside
        puzzle.section("Outside border cells must be outside")
        puzzle.when(grid.OutsideGrid(C), symbols["outside"](C))
        do_not_show_outside(symbols["outside"](cell), grid)

        # Rule 2: Sheep must be inside, wolves must be outside
        if sheep_facts:
            puzzle.section("Sheep constraints")
            puzzle.when(Sheep(C), symbols["inside"](C))

        if wolf_facts:
            puzzle.section("Wolf constraints")
            puzzle.when(Wolf(C), symbols["outside"](C))

        # Rule 3: Both inside and outside regions must be contiguous
        symbols.make_contiguous("inside")
        symbols.make_contiguous("outside", anchor_cell=grid.OutsideGrid(C))

        # Rule 4: Slitherlink clue constraints
        puzzle.section("Slitherlink clue constraints")

        puzzle.comment("Efficient handling for 0 clues")
        for t in ("inside", "outside"):
            puzzle.forbid(
                Clue(loc=C, num=0),
                symbols[t](loc=C),
                Not(symbols[t](loc=C_adj)),
                grid.Orthogonal(C, C_adj),
            )

        puzzle.comment("General handling for 1/2/3 clues")
        # Count outside neighbors when the clue cell is inside
        puzzle.count_constraint(
            count_over=cell_adj,
            condition=[
                grid.orthogonal(),
                symbols["outside"](loc=cell_adj),
            ],
            when=[Clue(loc=cell, num=N), N > 0, symbols["inside"](loc=cell)],
            exactly=N,
        )

        # Count inside neighbors when the clue cell is outside
        puzzle.count_constraint(
            count_over=cell_adj,
            condition=[
                grid.orthogonal(),
                symbols["inside"](loc=cell_adj),
            ],
            when=[Clue(loc=cell, num=N), N > 0, symbols["outside"](loc=cell)],
            exactly=N,
        )

        # Helper for rectangular grids: no checkerboard patterns
        if isinstance(grid, RectangularGrid):
            grid.forbid_checkerboard(symbols["inside"])

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Slitherlink solver.

        Returns:
            Dictionary with rendering configuration for Slitherlink
        """
        return {
            "puzzle_symbols": {
                0: RenderSymbol("0", Color.BRIGHT_BLUE),
                1: RenderSymbol("1", Color.BRIGHT_BLUE),
                2: RenderSymbol("2", Color.BRIGHT_BLUE),
                3: RenderSymbol("3", Color.BRIGHT_BLUE),
                "S": RenderSymbol("S", Color.BRIGHT_WHITE),
                "W": RenderSymbol("W", Color.BRIGHT_RED),
            },
            "predicates": {
                "inside": {"symbol": None, "background": BgColor.BRIGHT_GREEN},
            },
            "join_char": "",
        }
