from typing import Any

from aspuzzle.grids.rendering import Color, RenderSymbol
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import ANY, Predicate, create_variables


class Minesweeper(Solver):
    solver_name = "Minesweeper puzzle solver"
    supported_symbols = list(range(10)) + ["."]
    default_config = {"num_mines": None}

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Define predicates
        Number = Predicate.define("number", ["loc", "num"], show=False)
        N = create_variables("N")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define clues
        puzzle.blank_line(segment="Clues")
        puzzle.fact(
            *[Number(loc=grid.Cell(*loc), num=num) for loc, num in grid_data],
            segment="Clues",
        )

        # Define mine placement
        symbols = SymbolSet(grid).add_symbol("mine").excluded_symbol(Number(loc=cell, num=ANY))

        # Rule 1: Each number indicates exactly how many mines are adjacent
        puzzle.section("Numbers indicate the number of adjacent mines")
        puzzle.count_constraint(
            count_over=cell_adj,
            condition=[
                grid.VertexSharing(cell1=cell, cell2=cell_adj),
                symbols["mine"](loc=cell_adj),
            ],
            when=Number(loc=cell, num=N),
            exactly=N,
        )

        # (Optional) Rule 2: Global mine count constraint
        if config["num_mines"]:
            puzzle.section("Mine count constraint")
            puzzle.count_constraint(count_over=cell, condition=symbols["mine"](loc=cell), exactly=config["num_mines"])

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Minesweeper solver.

        Returns:
            Dictionary with rendering configuration for Minesweeper
        """
        return {
            "puzzle_symbols": {
                0: RenderSymbol("0", Color.WHITE),
                1: RenderSymbol("1", Color.BLUE),
                2: RenderSymbol("2", Color.GREEN),
                3: RenderSymbol("3", Color.RED),
                4: RenderSymbol("4", Color.MAGENTA),
                5: RenderSymbol("5", Color.CYAN),
                6: RenderSymbol("6", Color.YELLOW),
                7: RenderSymbol("7", Color.WHITE),
                8: RenderSymbol("8", Color.WHITE),
            },
            "predicates": {
                "mine": {"symbol": "*", "color": Color.RED},
            },
        }
