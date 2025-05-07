from typing import Any

from aspuzzle.grids.rendering import Color
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import ANY, Predicate, create_variables


class Minesweeper(Solver):
    solver_name = "Minesweeper puzzle solver"
    supported_symbols = list(range(10)) + ["."]
    default_config = {"num_mines": None}

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data

        # Define predicates
        Number = Predicate.define("number", ["loc", "num"], show=False)
        N = create_variables("N")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define clues
        puzzle.blank_line(segment="Clues")
        puzzle.fact(
            *[Number(loc=grid.Cell(row=r, col=c), num=num) for r, c, num in grid_data],
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
                0: {"color": Color.WHITE},
                1: {"color": Color.BLUE},
                2: {"color": Color.GREEN},
                3: {"color": Color.RED},
                4: {"color": Color.MAGENTA},
                5: {"color": Color.CYAN},
                6: {"color": Color.YELLOW},
                7: {"color": Color.WHITE},
                8: {"color": Color.WHITE},
            },
            "predicate_renders": {
                "mine": {
                    "symbol": "*",
                    "color": Color.RED,
                },
            },
        }
