from typing import Any

from aspuzzle.grids.base import do_not_show_outside
from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.grids.rendering import BgColor, Color, RenderSymbol
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import ANY, Predicate, create_variables


class Cave(Solver):
    solver_name = "Cave/Bag/Corral puzzle solver"
    supported_symbols = list(range(1, 30)) + ["."]  # Support numbers 1-29 and empty cells
    # TODO: Support for defining grids that have numbers > 9

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Define predicates
        Number = Predicate.define("number", ["loc", "value"], show=False)
        CanSee = Predicate.define("can_see", ["from_loc", "dir", "index", "position"], show=False)

        # Create variables
        C, Dir, Pos, Idx, Delta, N = create_variables("C", "Dir", "Pos", "Idx", "Delta", "N")
        cell = grid.cell()
        cell_seen = grid.cell(suffix="seen")

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

        # Define the base case: a cell can see itself (along all lines it sits on)
        puzzle.when(
            [
                Number(loc=cell, value=ANY),
                grid.OrderedLine(direction=Dir, index=Idx, position=Pos, loc=cell),
            ],
            let=CanSee(from_loc=cell, dir=Dir, index=Idx, position=Pos),
        )

        # Define the recursive case: We extend CanSee forwards and backwards whilever there are cave cells
        puzzle.when(
            [
                CanSee(from_loc=cell, dir=Dir, index=Idx, position=Pos),
                grid.OrderedLine(direction=Dir, index=Idx, position=Pos + Delta, loc=cell_seen),
                Delta.in_([-1, 1]),
                symbols["cave"](loc=cell_seen),
            ],
            let=CanSee(from_loc=cell, dir=Dir, index=Idx, position=Pos + Delta),
        )

        # Count constraint: Numbered cells indicate how many cave cells they can see including themselves
        puzzle.count_constraint(
            count_over=cell_seen,
            condition=[
                CanSee(from_loc=cell, dir=Dir, index=Idx, position=Pos),
                grid.OrderedLine(direction=Dir, index=Idx, position=Pos, loc=cell_seen),
            ],
            when=Number(loc=cell, value=N),
            exactly=N,
        )

        # Supplementary Rule: No checkerboard patterns
        if isinstance(grid, RectangularGrid):
            grid.forbid_checkerboard(symbols["cave"], segment=symbols.name)

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Cave puzzle solver.

        Returns:
            Dictionary with rendering configuration
        """
        # For numbers 1-9, use the digit as is
        puzzle_symbols = {i: RenderSymbol(str(i), Color.BRIGHT_BLUE) for i in range(1, 10)}

        # For numbers 10+, use # with a distinctive color
        for i in range(10, 30):
            puzzle_symbols[i] = RenderSymbol("#", Color.RED)

        return {
            "puzzle_symbols": puzzle_symbols,
            "predicates": {
                "cave": {"symbol": None, "background": None},
                "wall": {"symbol": None, "background": BgColor.BRIGHT_BLACK},
            },
            "join_char": "",
        }
