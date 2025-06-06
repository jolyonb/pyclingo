from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from aspuzzle.grids.base import Grid, GridCellData
from aspuzzle.grids.rendering import RenderItem, RenderSymbol, colorize
from aspuzzle.puzzle import Puzzle, cached_predicate
from pyclingo import Not, Predicate, RangePool, create_variables

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_RAW_INPUT_TYPE


class RectangularGrid(Grid):
    """Module for rectangular grid-based puzzles with rows and columns. Note that this uses 1-based indexing!"""

    def __init__(
        self,
        puzzle: Puzzle,
        rows: int,
        cols: int,
        name: str = "grid",
        primary_namespace: bool = True,
    ):
        """Initialize a grid module with specified dimensions."""
        super().__init__(puzzle, name, primary_namespace)

        assert isinstance(rows, int)
        assert isinstance(cols, int)

        self.rows = rows
        self.cols = cols

    def with_new_puzzle(self, puzzle: Puzzle) -> RectangularGrid:
        """Return a copy of this Grid with a new puzzle."""
        return type(self)(
            puzzle=puzzle, rows=self.rows, cols=self.cols, name=self._name, primary_namespace=self._namespace == ""
        )

    @property
    def cell_fields(self) -> list[str]:
        """Returns the list of field names associated with the Cell predicate for this grid"""
        return ["row", "col"]

    @property
    def cell_var_names(self) -> list[str]:
        """Returns the default list of variable names for the Cell predicate for this grid"""
        return ["R", "C"]

    @property
    def direction_vectors(self) -> list[tuple[str, tuple[int, ...]]]:
        """Returns the list of directions and vectors for this grid"""
        return [
            ("n", (-1, 0)),
            ("ne", (-1, 1)),
            ("e", (0, 1)),
            ("se", (1, 1)),
            ("s", (1, 0)),
            ("sw", (1, -1)),
            ("w", (0, -1)),
            ("nw", (-1, -1)),
        ]

    @property
    def orthogonal_direction_names(self) -> list[str]:
        """Returns the list of orthogonal direction names for this grid"""
        return ["n", "e", "s", "w"]

    @property
    def opposite_directions(self) -> list[tuple[str, str]]:
        """Returns the list of opposite direction names for this grid"""
        return [
            ("n", "s"),
            ("ne", "sw"),
            ("e", "w"),
            ("se", "nw"),
            ("s", "n"),
            ("sw", "ne"),
            ("w", "e"),
            ("nw", "se"),
        ]

    @property
    def line_direction_names(self) -> list[str]:
        """Returns the list of line direction names for rectangular grid"""
        return ["e", "s"]  # e for rows, s for columns

    @property
    def line_direction_descriptions(self) -> dict[str, str]:
        """Returns descriptions for rectangular grid lines"""
        return {"e": "row", "s": "column"}

    @property
    def line_characters(self) -> dict[str, str]:
        """Get ASCII line characters for direction combinations in rectangular grids."""
        return {
            "ew": "─",  # horizontal line
            "ns": "│",  # vertical line
            "es": "┌",  # top-left corner
            "sw": "┐",  # top-right corner
            "en": "└",  # bottom-left corner
            "nw": "┘",  # bottom-right corner
            "we": "─",  # horizontal line (reverse)
            "sn": "│",  # vertical line (reverse)
            "se": "┌",  # top-left corner (reverse)
            "ws": "┐",  # top-right corner (reverse)
            "ne": "└",  # bottom-left corner (reverse)
            "wn": "┘",  # bottom-right corner (reverse)
        }

    def get_line_count(self, direction: str) -> int:
        """Returns the number of lines in the specified direction for a rectangular grid"""
        if direction == "e":  # rows
            return self.rows
        elif direction == "s":  # columns
            return self.cols
        else:
            raise ValueError(f"Unknown direction: {direction}")

    @property
    @cached_predicate
    def Cell(self) -> type[Predicate]:
        """Get the Cell predicate for this grid."""
        Cell = Predicate.define("cell", self.cell_fields, namespace=self.namespace, show=False)

        R, C = create_variables("R", "C")

        # Define grid cells
        self.section("Define cells in the grid")
        self.when(
            [
                R.in_(RangePool(1, self.rows)),
                C.in_(RangePool(1, self.cols)),
            ],
            Cell(R, C),
        )

        return Cell

    @property
    @cached_predicate
    def OutsideGrid(self) -> type[Predicate]:
        """Get the OutsideGrid predicate identifying cells in the outside border."""
        Outside = Predicate.define("outside_grid", ["loc"], namespace=self.namespace, show=False)

        R, C = create_variables("R", "C")
        cell = self.Cell(R, C)

        self.section("Define outside border cells")

        # Top and bottom rows
        self.when(
            [
                R.in_([0, self.rows + 1]),
                C.in_(RangePool(0, self.cols + 1)),
            ],
            Outside(loc=cell),
        )
        # Left and right columns (but not double counting the corners)
        self.when(
            [
                C.in_([0, self.cols + 1]),
                R.in_(RangePool(1, self.rows)),
            ],
            Outside(loc=cell),
        )
        # Create cell locations in the outside border
        self.when(Outside(loc=cell), let=self.Cell(R, C))

        # We've included the outside border
        self._has_outside_border = True

        return Outside

    @property
    @cached_predicate
    def Line(self) -> type[Predicate]:
        """Get the Line predicate defining major lines in the grid."""
        Line = Predicate.define("line", ["direction", "index", "loc"], namespace=self.namespace, show=False)

        R, C = create_variables("R", "C")
        cell = self.Cell(row=R, col=C)

        self.section("Define major lines in the grid")

        # For rectangular grids, define rows (direction E) and columns (direction S)
        # Row lines: all cells in the same row
        self.when(
            [
                cell,
                R.in_(RangePool(1, self.rows)),
            ],
            Line(direction="e", index=R, loc=cell),
        )

        # Column lines: all cells in the same column
        self.when(
            [
                cell,
                C.in_(RangePool(1, self.cols)),
            ],
            Line(direction="s", index=C, loc=cell),
        )

        return Line

    @property
    @cached_predicate
    def OrderedLine(self) -> type[Predicate]:
        """
        Get the OrderedLine predicate defining major lines in the grid with position ordering.

        For a rectangular grid, this defines rows (direction 'e') and columns (direction 's')
        with a position parameter indicating the ordinal position along that line.
        """
        OrderedLine = Predicate.define(
            "ordered_line", ["direction", "index", "position", "loc"], namespace=self.namespace, show=False
        )

        R, C = create_variables("R", "C")
        cell = self.Cell(row=R, col=C)

        self.section("Define ordered positions along major lines in the grid")

        # For rectangular grids, define rows (direction E) and columns (direction S)
        # Row lines: all cells in the same row, with column number as position
        self.when(
            [
                cell,
                R.in_(RangePool(1, self.rows)),
                C.in_(RangePool(1, self.cols)),
            ],
            OrderedLine(direction="e", index=R, position=C, loc=cell),
        )

        # Column lines: all cells in the same column, with row number as position
        self.when(
            [
                cell,
                R.in_(RangePool(1, self.rows)),
                C.in_(RangePool(1, self.cols)),
            ],
            OrderedLine(direction="s", index=C, position=R, loc=cell),
        )

        return OrderedLine

    @classmethod
    def from_config(
        cls,
        puzzle: Puzzle,
        config: dict[str, Any],
        name: str = "grid",
        primary_namespace: bool = True,
    ) -> RectangularGrid:
        """Create a rectangular grid from configuration."""
        # Get explicit grid parameters if provided
        grid_params = config.get("grid_params", {}).copy()
        grid: list[str] | list[list[str | int]] | None = config.get("grid")

        # Determine rows
        if "rows" in grid_params:
            rows = grid_params["rows"]
        elif grid is not None:
            rows = len(grid)
        else:
            raise ValueError("Grid rows must be specified in grid_params or grid")

        # Determine cols
        if "cols" in grid_params:
            cols = grid_params["cols"]
        elif grid is not None:
            cols = len(grid[0])
        else:
            raise ValueError("Grid cols must be specified in grid_params or grid")

        # Create and return the grid
        return cls(
            puzzle,
            rows=rows,
            cols=cols,
            name=name,
            primary_namespace=primary_namespace,
        )

    def parse_grid(
        self, grid_data: list[str] | list[list[str | int]], map_to_integers: bool = False
    ) -> list[GridCellData]:
        """
        Parse a rectangular grid into organized structures, ignoring any "." characters.

        Args:
            grid_data: The raw grid data as a list of strings, or a list of lists of strings or integers
            map_to_integers: Whether to convert symbols to unique integers

        Returns:
            List of (loc, value) tuples for non-empty cells
        """
        rows = self.rows
        cols = self.cols

        # Turn the input grid_data into a list of lists version as necessary
        clean_grid_data: list[list[str | int]] = [e if isinstance(e, list) else list(e) for e in grid_data]

        # Validate grid dimensions
        if len(clean_grid_data) != rows:
            raise ValueError(f"Expected {rows} rows in grid, got {len(clean_grid_data)}")
        for row in clean_grid_data:
            if len(row) != cols:
                raise ValueError(f"Expected {cols} cols in row, got {len(row)}")

        symbol_to_id = {}
        if map_to_integers:
            # First, collect all unique symbols
            unique_symbols = set()
            for row in clean_grid_data:
                for char in row:
                    if char != ".":
                        unique_symbols.add(char)

            # Create mapping from symbols to integer IDs
            # First map numbers to themselves (if they exist)
            used_ids = set()

            # Map numeric symbols first
            for symbol in unique_symbols:
                if isinstance(symbol, int) or (isinstance(symbol, str) and symbol.isdigit()):
                    id_num = int(symbol)
                    symbol_to_id[symbol] = id_num
                    used_ids.add(id_num)

            # Map non-numeric symbols to unused integers
            next_id = 1
            for symbol in sorted(unique_symbols):  # Sort for consistency
                if symbol not in symbol_to_id:
                    while next_id in used_ids:
                        next_id += 1
                    symbol_to_id[symbol] = next_id
                    used_ids.add(next_id)
                    next_id += 1

        # Parse cells
        cells: list[GridCellData] = []

        for r, line in enumerate(clean_grid_data):
            for c, char in enumerate(line):
                # Special case: ignore "." characters
                if char == ".":
                    continue

                # Process the value
                value: int | str
                if map_to_integers and char in symbol_to_id:
                    value = symbol_to_id[char]
                else:
                    value = int(char) if isinstance(char, str) and char.isdigit() else char

                # Add to cells list
                cell_entry = ((r + 1, c + 1), value)
                cells.append(cell_entry)

        return cells

    def add_vector_to_cell(self, cell_pred: Predicate, vector_pred: Predicate) -> Predicate:
        """Add a vector to a cell in rectangular coordinates."""
        # Extract coordinates
        row = getattr(cell_pred, "row")
        col = getattr(cell_pred, "col")
        dr = getattr(vector_pred, "row")
        dc = getattr(vector_pred, "col")

        # Create new cell with added coordinates
        return self.Cell(row=row + dr, col=col + dc)

    def forbid_2x2_blocks(self, symbol_predicate: type[Predicate], **fixed_fields: PREDICATE_RAW_INPUT_TYPE) -> None:
        """
        Forbid 2x2 blocks of a specific symbol/predicate in a rectangular grid.

        Args:
            symbol_predicate: The predicate class representing the symbol to constrain
            **fixed_fields: Fixed field values for the predicate (for multi-field predicates)

        Example:
            # Forbid 2x2 blocks of mines
            grid.forbid_2x2_blocks(symbols["mine"])

            # For a predicate with multiple fields, specify which fields to fix
            grid.forbid_2x2_blocks(symbols["digit"], value=Var)  # Forbid 2x2 blocks of any individual digit
        """
        self.puzzle.section(f"Forbid 2x2 blocks of {symbol_predicate.__name__}")

        R, C = create_variables("R", "C")
        top_left_cell = self.Cell(row=R, col=C)
        top_right_cell = self.Cell(row=R, col=C + 1)
        bottom_left_cell = self.Cell(row=R + 1, col=C)
        bottom_right_cell = self.Cell(row=R + 1, col=C + 1)

        self.puzzle.forbid(
            symbol_predicate(loc=top_left_cell, **fixed_fields),
            symbol_predicate(loc=top_right_cell, **fixed_fields),
            symbol_predicate(loc=bottom_left_cell, **fixed_fields),
            symbol_predicate(loc=bottom_right_cell, **fixed_fields),
            top_left_cell,
            bottom_right_cell,
        )

    def forbid_checkerboard(self, symbol_predicate: type[Predicate], **fixed_fields: PREDICATE_RAW_INPUT_TYPE) -> None:
        """
        Forbids a 2x2 block checkerboard pattern of a given predicate in a rectangular grid.
        If the symbol is contiguous and not(symbol) is also contiguous, this configuration is invalid, as
        something must be surrounded.

        Args:
            symbol_predicate: The predicate class representing the symbol to constrain
            **fixed_fields: Fixed field values for the predicate (for multi-field predicates)
        """
        self.puzzle.section(f"Forbid disconnecting checkerboard pattern for {symbol_predicate.__name__}")

        R, C = create_variables("R", "C")
        top_left_cell = self.Cell(row=R, col=C)
        top_right_cell = self.Cell(row=R, col=C + 1)
        bottom_left_cell = self.Cell(row=R + 1, col=C)
        bottom_right_cell = self.Cell(row=R + 1, col=C + 1)

        top_left = symbol_predicate(loc=top_left_cell, **fixed_fields)
        top_right = symbol_predicate(loc=top_right_cell, **fixed_fields)
        bottom_right = symbol_predicate(loc=bottom_right_cell, **fixed_fields)
        bottom_left = symbol_predicate(loc=bottom_left_cell, **fixed_fields)

        # Forbid checkerboard on one diagonal
        self.puzzle.forbid(
            top_left,
            bottom_right,
            Not(top_right),
            Not(bottom_left),
            top_left_cell,
            bottom_right_cell,
        )

        # Forbid checkerboard on the other diagonal
        self.puzzle.forbid(
            top_right,
            bottom_left,
            Not(top_left),
            Not(bottom_right),
            top_left_cell,
            bottom_right_cell,
        )

    def render_ascii(
        self,
        puzzle_render_items: list[RenderItem],
        predicate_render_items: dict[int, list[RenderItem]],
        render_config: dict[str, Any],
        use_colors: bool = True,
    ) -> str:
        """
        Render the rectangular grid as ASCII text.

        This method takes preprocessed rendering items and converts them into an ASCII
        representation of the grid. Rendering is applied in order of priority, with higher
        priority items rendered later (on top).

        Args:
            puzzle_render_items: List of RenderItem objects for the puzzle symbols
            predicate_render_items: Dictionary mapping priority levels to lists of RenderItem objects
            render_config: Additional rendering configuration including:
                - 'join_char': Character to use in joining cells (default: " ")
            use_colors: Whether to use ANSI colors in the output

        Returns:
            ASCII string representation of the grid
        """
        # Construct the dot representation
        dot = render_config.get("puzzle_symbols", {}).get(".", RenderSymbol("."))

        # Initialize grid with dots
        grid: list[list[RenderSymbol]] = [
            [dataclasses.replace(dot) for _ in range(self.cols)] for _ in range(self.rows)
        ]

        # Combine all render items in priority order
        # Puzzle symbols are lowest priority
        all_render_items = list(puzzle_render_items)
        # Add predicate items in priority order
        for priority in sorted(predicate_render_items.keys()):
            all_render_items.extend(predicate_render_items[priority])

        # Process all render items
        for item in all_render_items:
            # Extract row/col from the location predicate, adjusting for 1-based indexing
            loc = item.loc
            grid_row = loc["row"].value - 1
            grid_col = loc["col"].value - 1

            # Skip if outside grid bounds
            if grid_row < 0 or grid_row >= self.rows or grid_col < 0 or grid_col >= self.cols:
                continue

            # Update what we're rendering
            render_symbol: RenderSymbol = grid[grid_row][grid_col]
            if item.symbol:
                render_symbol.symbol = item.symbol
            if item.color:
                render_symbol.color = item.color
            if item.background:
                render_symbol.bgcolor = item.background

        # Convert grid to string
        rows = []
        join_char = render_config.get("join_char", " ")
        for row_in_grid in grid:
            row_str = []
            for render_symbol in row_in_grid:
                if use_colors:
                    row_str.append(colorize(render_symbol.symbol, render_symbol.color, render_symbol.bgcolor))
                else:
                    row_str.append(render_symbol.symbol)

            rows.append(join_char.join(row_str))

        return "\n".join(rows)
