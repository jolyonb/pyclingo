from typing import Any

from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.grids.rendering import Color
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import Predicate, RangePool, create_variables


class Sudoku(Solver):
    """
    A generalized Sudoku puzzle solver.

    Features:
    - Handles standard 9x9 puzzles with 3x3 blocks
    - Supports any N^2×N^2 grid with N×N blocks (4×4, 16×16, etc.)
    - Supports non-square blocks (e.g., 6×6 with 2×3 blocks)
    - Handles number ranges from 1 to grid size
    """

    solver_name = "Sudoku puzzle solver"
    # Digits 1-9 and "." for empty cells by default, but gets modified for non-9x9 puzzles
    supported_symbols = list(range(1, 10)) + ["."]
    supported_grid_types = (RectangularGrid,)
    default_config = {
        "block_rows": None,  # Number of rows in a block
        "block_cols": None,  # Nimber of columns in a block
    }

    block_rows: int
    block_cols: int

    def validate_config(self) -> None:
        """Validate the Sudoku configuration."""
        grid = self.grid
        assert isinstance(grid, RectangularGrid)

        # Check that the grid is square
        if grid.rows != grid.cols:
            raise ValueError(f"Sudoku requires a square grid. Got {grid.rows}x{grid.cols}")

        # Get or calculate block dimensions
        self.block_rows = self.config["block_rows"]
        self.block_cols = self.config["block_cols"]

        grid_size = grid.rows

        # Auto-determine block size for perfect square grids (4×4, 9×9, 16×16, etc.)
        if self.block_rows is None and self.block_cols is None:
            # Try to find a perfect square factor
            n = int(grid_size**0.5)
            if n**2 == grid_size:
                self.block_rows = self.block_cols = n
            else:
                # For non-perfect squares like 6×6, we need explicit configuration
                raise ValueError(
                    f"For non-square-rooted grids like {grid_size}×{grid_size}, "
                    f"you must specify block_rows and block_cols in the configuration"
                )

        if self.block_rows is None:
            raise ValueError("block_rows must be specified in the configuration")
        if self.block_cols is None:
            raise ValueError("block_cols must be specified in the configuration")

        # Validate that block dimensions multiply to give the grid size
        if self.block_rows * self.block_cols != grid_size:
            raise ValueError(
                f"Block dimensions ({self.block_rows}×{self.block_cols}) "
                f"must multiply to give the grid size ({grid_size})"
            )

        # Update supported symbols depending on grid size
        self.supported_symbols = list(range(1, grid_size + 1)) + ["."]

    def construct_puzzle(self) -> None:
        """Construct the Sudoku puzzle rules."""
        puzzle, grid, config, grid_data = self.unpack_data()
        assert isinstance(grid, RectangularGrid)

        grid_size = grid.rows
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
                N == 1 + (C - 1) // self.block_cols + self.block_rows * ((R - 1) // self.block_rows),
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
        assert isinstance(self.grid, RectangularGrid)
        grid_size = self.grid.rows

        puzzle_symbols = {
            i: {
                "symbol": str(i) if i <= 9 else chr(ord("A") + i - 10),
                "color": Color.BLUE,
            }
            for i in range(1, grid_size + 1)
        }

        return {
            "puzzle_symbols": puzzle_symbols,
            "predicates": {
                "number": {"value": "value", "color": Color.GREEN},
            },
        }
