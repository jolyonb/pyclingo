from typing import Any

from aspuzzle.grids.base import do_not_show_outside
from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.grids.rendering import BgColor, Color
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import ANY, Count, Predicate, create_variables


class Cave(Solver):
    solver_name = "Cave/Bag/Corral puzzle solver"
    supported_symbols = list(range(1, 30)) + ["."]  # Support numbers 1-29 and empty cells
    # TODO: Support for defining grids that have numbers > 9

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Define predicates
        Number = Predicate.define("number", ["loc", "value"], show=False)
        Visible = Predicate.define("visible", ["loc", "dir", "distance"], show=False)

        # Create variables
        C, Dir, Dist, T, N = create_variables("C", "Dir", "Dist", "T", "N")
        cell = grid.cell()
        vec = grid.cell(suffix="vec")
        cell_plus_vec = grid.add_vector_to_cell(cell, vec)

        # Define numbers from the input grid
        puzzle.section("Define numbered cells", segment="Clues")
        puzzle.fact(*[Number(loc=grid.Cell(*loc), value=value) for loc, value in grid_data], segment="Clues")

        # Define cave/wall cells using a symbol set
        symbols = SymbolSet(grid, fill_all_squares=True).add_symbol("cave").add_symbol("wall")

        # Rule 1: All outside border cells are walls
        puzzle.section("Outside border cells must be walls")
        puzzle.when(grid.OutsideGrid(C), symbols["wall"](C))
        do_not_show_outside(symbols["wall"](cell), grid)

        # Rule 2: All cave cells must form a single connected group
        symbols.make_contiguous("cave")

        # Rule 3: All wall cells must be connected to the edge of the grid
        symbols.make_contiguous("wall", anchor_cell=grid.OutsideGrid(C))

        # Rule 4: All numbered cells must be part of the cave
        puzzle.section("Numbered cells must be caves")
        puzzle.when(Number(loc=C, value=ANY), symbols["cave"](C))

        # Rule 5: Line-of-sight count for numbered cells
        puzzle.section("Line-of-sight counting")

        # Base case: Number cells see adjacent cells in orthogonal directions
        puzzle.when(
            [
                Number(loc=cell, value=ANY),
                grid.Direction(name=Dir, vector=vec),
                grid.OrthogonalDirections(Dir),
                symbols["cave"](loc=cell_plus_vec),
            ],
            let=Visible(loc=cell, dir=Dir, distance=1),
        )

        # Recursive case: Continue seeing in the same direction until hitting a wall
        # TODO: The add_vector_to_cell method with a vec_multiplier might not work on a triangular grid
        puzzle.when(
            [
                Visible(loc=cell, dir=Dir, distance=Dist),
                grid.Direction(name=Dir, vector=vec),
                grid.OrthogonalDirections(Dir),
                symbols["cave"](loc=grid.add_vector_to_cell(cell, vec, vec_multiplier=Dist + 1)),
            ],
            Visible(loc=cell, dir=Dir, distance=Dist + 1),
        )

        # Count constraint: For each numbered cell, the number indicates how many cave cells it can see plus itself
        count_expr = T == Count(element=(Dir, Dist), condition=Visible(loc=cell, dir=Dir, distance=Dist))
        puzzle.when(
            [Number(loc=cell, value=N), count_expr],
            N == T + 1,  # +1 for the number cell itself
        )

        # Supplementary Rule: No checkerboard patterns
        if isinstance(grid, RectangularGrid):
            grid.forbid_checkerboard(symbols["cave"])

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Cave puzzle solver.

        Returns:
            Dictionary with rendering configuration
        """
        # For numbers 1-9, use the digit as is
        puzzle_symbols = {i: {"symbol": str(i), "color": Color.BRIGHT_BLUE} for i in range(1, 10)}

        # For numbers 10+, use # with a distinctive color
        for i in range(10, 30):
            puzzle_symbols[i] = {"symbol": "#", "color": Color.RED}

        return {
            "puzzle_symbols": puzzle_symbols,
            "predicates": {
                "cave": {"symbol": None, "background": None},
                "wall": {"symbol": None, "background": BgColor.BRIGHT_BLACK},
            },
            "join_char": "",
        }
