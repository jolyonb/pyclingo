from typing import Any

from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.grids.rendering import Color
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import Predicate, RangePool, create_variables


class Sudoku(Solver):
    """Sudoku puzzle solver."""

    solver_name = "Sudoku puzzle solver"
    # Digits 1-9 and "." for empty cells
    supported_symbols = list(range(1, 10)) + ["."]
    supported_grid_types = (RectangularGrid,)

    def validate_config(self) -> None:
        """Validate the Sudoku configuration."""
        grid = self.grid
        assert isinstance(grid, RectangularGrid)

        # Check that the grid is square
        if grid.rows != grid.cols:
            raise ValueError(f"Sudoku requires a square grid. Got {grid.rows}x{grid.cols}")

        # For the moment, require a 9x9 grid
        if grid.rows != 9 or grid.cols != 9:
            raise ValueError(f"Sudoku requires a 9x9 grid (until we implement variations). Got {grid.rows}x{grid.cols}")

    def construct_puzzle(self) -> None:
        """Construct the Sudoku puzzle rules."""
        puzzle, grid, config, grid_data = self.unpack_data()
        assert isinstance(grid, RectangularGrid)

        grid_size = grid.rows
        box_size = 3  # Hard-coded for now (standard 9x9 Sudoku with 3x3 boxes)
        R, C, C1, C2, D, N, Idx = create_variables("R", "C", "C1", "C2", "D", "N", "Idx")

        # Rule 1: Add numbers 1-9 to the grid, one per cell
        symbols = SymbolSet(grid, fill_all_squares=True)
        symbols.add_range_symbol(name="number", pool=RangePool(1, grid_size), show=True)
        Number = symbols["number"]

        # Rule 2: Each digit can appear only once in each row and column
        puzzle.section("Each digit appears at most once in each row and column")
        puzzle.when(
            [
                Number(loc=C1, value=N),
                Number(loc=C2, value=N),
                grid.Line(direction=D, index=Idx, loc=C1),
                grid.Line(direction=D, index=Idx, loc=C2),
            ],
            let=(C1 == C2),
        )

        # Define blocks
        puzzle.section("Define block membership")
        Block = Predicate.define("block", ["loc", "block_id"], show=False)
        puzzle.when(
            [
                grid.Cell(row=R, col=C),
                # Calculate block ID using integer division: 1 + (C-1)//box_size + box_size*((R-1)//box_size)
                N == 1 + ((C - 1) // box_size) + box_size * ((R - 1) // box_size),
            ],
            let=Block(loc=grid.Cell(row=R, col=C), block_id=N),
        )

        # Rule 3: Each digit can appear only once in each block
        puzzle.section("Each digit appears at most once in each block")
        puzzle.when(
            [
                Number(loc=C1, value=N),
                Number(loc=C2, value=N),
                Block(C1, block_id=Idx),
                Block(C2, block_id=Idx),
            ],
            let=(C1 == C2),
        )

        # Add clues to the puzzle - these are the fixed starting values
        puzzle.fact(
            *[Number(loc=grid.Cell(*loc), value=value) for loc, value in grid_data],
            segment="Clues",
        )

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Sudoku solver.

        Returns:
            Dictionary with rendering configuration for Sudoku
        """
        return {
            "puzzle_symbols": {i: {"symbol": str(i), "color": Color.BLUE} for i in range(1, 10)},
            "predicates": {
                "number": {"value": "value", "color": Color.GREEN},
            },
        }
