from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aspuzzle.grids.base import Grid, GridCellData
from aspuzzle.grids.rendering import BgColor, Color, RenderItem, colorize
from aspuzzle.puzzle import Puzzle, cached_predicate
from pyclingo import Min, Not, Predicate, RangePool, create_variables

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
    def line_direction_names(self) -> list[str]:
        """Returns the list of line direction names for rectangular grid"""
        return ["e", "s"]  # e for rows, s for columns

    @property
    def line_direction_descriptions(self) -> dict[str, str]:
        """Returns descriptions for rectangular grid lines"""
        return {"e": "row", "s": "column"}

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

    def find_anchor_cell(
        self,
        condition_predicate: type[Predicate],
        cell_field: str,
        anchor_name: str,
        fixed_fields: dict[str, Any] | None = None,
        preserved_fields: list[str] | None = None,
        segment: str | None = None,
    ) -> type[Predicate]:
        """
        Find the lexicographically minimum cell that satisfies the given condition.
        The anchor is the cell with minimum row, and among those, minimum column.

        Args:
            condition_predicate: The predicate class to check
            cell_field: The name of the field that contains the cell location
            anchor_name: Name for the anchor predicate
            fixed_fields: Dictionary of field names to values for the condition predicate
            preserved_fields: List of field names from fixed_fields to include in the anchor predicate
            segment: Segment to publish these rules to

        Returns:
            The anchor predicate class that marks the anchor cell
        """
        self.puzzle.section(f"Find anchor cell for {condition_predicate.__name__}", segment=segment)

        if fixed_fields is None:
            fixed_fields = {}

        if preserved_fields is None:
            preserved_fields = []

        # Validate that preserved fields are actually in fixed_fields
        for field in preserved_fields:
            if field not in fixed_fields:
                raise ValueError(f"Preserved field '{field}' not found in fixed_fields")

        # Define the anchor predicate with the cell field and any preserved fields
        anchor_field_names = [cell_field] + preserved_fields
        AnchorPred = Predicate.define(anchor_name, anchor_field_names, namespace=self.namespace, show=False)

        R, C, MinR, MinC = create_variables("R", "C", "MinR", "MinC")
        cell = self.Cell(row=R, col=C)

        # Build the condition with fixed fields and cell
        condition_args = {**fixed_fields, cell_field: cell}

        # Find minimum row among cells that satisfy the condition
        MinRowPred = Predicate.define(
            f"min_row_for_{anchor_name}", ["row"] + preserved_fields, namespace=self.namespace, show=False
        )

        # Build arguments for MinRowPred
        min_row_args = {"row": MinR}
        for field in preserved_fields:
            min_row_args[field] = fixed_fields[field]

        # Find the minimum row
        self.puzzle.when(
            Min(R, condition=[condition_predicate(**condition_args), R.in_(RangePool(1, self.rows))]).assign_to(MinR),
            MinRowPred(**min_row_args),
            segment=segment,
        )

        # Find minimum column among cells in the minimum row
        min_row_condition_args = {**fixed_fields, cell_field: self.Cell(row=MinR, col=C)}

        # Build the final anchor predicate arguments
        anchor_args = {cell_field: self.Cell(row=MinR, col=MinC)}
        for field in preserved_fields:
            anchor_args[field] = fixed_fields[field]

        self.puzzle.when(
            [
                MinRowPred(**min_row_args),
                Min(
                    C, condition=[condition_predicate(**min_row_condition_args), C.in_(RangePool(1, self.rows))]
                ).assign_to(MinC),
            ],
            AnchorPred(**anchor_args),
            segment=segment,
        )

        return AnchorPred

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
        grid: list[str] | None = config.get("grid")

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

    # In grids/rectangulargrid.py
    def parse_grid(self, grid_data: list[str], map_to_integers: bool = False) -> list[GridCellData]:
        """
        Parse a rectangular grid into organized structures, ignoring any "." characters.

        Args:
            grid_data: The raw grid data as a list of strings
            map_to_integers: Whether to convert symbols to unique integers

        Returns:
            List of (row, col, value) tuples for non-empty cells
        """
        rows = self.rows
        cols = self.cols

        # Validate grid dimensions
        if len(grid_data) != rows:
            raise ValueError(f"Expected {rows} rows in grid, got {len(grid_data)}")
        for row in grid_data:
            if len(row) != cols:
                raise ValueError(f"Expected {cols} cols in row, got {len(row)}")

        symbol_to_id = {}
        if map_to_integers:
            # First, collect all unique symbols
            unique_symbols = set()
            for row in grid_data:
                for char in row:
                    if char != ".":
                        unique_symbols.add(char)

            # Create mapping from symbols to integer IDs
            # First map numbers to themselves (if they exist)
            used_ids = set()

            # Map numeric symbols first
            for symbol in unique_symbols:
                if symbol.isdigit():
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
        cells = []

        for r, line in enumerate(grid_data):
            for c, char in enumerate(line):
                # Special case: ignore "." characters
                if char == ".":
                    continue

                # Process the value
                value: int | str
                if map_to_integers and char in symbol_to_id:
                    value = symbol_to_id[char]
                else:
                    value = int(char) if char.isdigit() else char

                # Add to cells list
                cell_entry = (r + 1, c + 1, value)
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
        puzzle_definition: list[GridCellData],
        solution: dict[str, list[Predicate]] | None = None,
        render_config: dict[str, Any] | None = None,
        use_colors: bool = True,
    ) -> str:
        """
        Render the rectangular grid as ASCII text.

        Args:
            puzzle_definition: List of (row, col, value) tuples defining the puzzle
            solution: Dictionary mapping predicate names to lists of predicate instances
            render_config: Configuration for rendering
            use_colors: Whether to use ANSI colors in the output

        Returns:
            ASCII string representation of the grid
        """
        render_config = render_config or {}

        # Initialize grid with dots
        grid: list[list[tuple[str, Color | None, BgColor | None]]] = [
            [(".", None, None) for _ in range(self.cols)] for _ in range(self.rows)
        ]

        # Process puzzle definition
        if puzzle_definition:
            puzzle_symbols = render_config.get("puzzle_symbols", {})

            # Place puzzle values on the grid
            for row, col, value in puzzle_definition:
                if value not in puzzle_symbols:
                    continue

                # Adjust for 1-based indexing
                grid_row = row - 1
                grid_col = col - 1

                # Skip if outside grid bounds
                if grid_row < 0 or grid_row >= self.rows or grid_col < 0 or grid_col >= self.cols:
                    continue

                # Use configured symbol
                symbol_config = puzzle_symbols[value]
                color = None
                background = None
                if isinstance(symbol_config, str):
                    display_value = symbol_config
                elif isinstance(symbol_config, dict):
                    display_value = symbol_config.get("symbol", str(value))
                    color = symbol_config.get("color", None)
                    background = symbol_config.get("background", None)
                else:
                    display_value = str(value)

                grid[grid_row][grid_col] = (display_value, color, background)

        # Process solution if provided
        if solution:
            predicate_styling = render_config.get("predicates", {})

            # Only render predicates that have configuration
            predicates_to_render = []
            for pred_name in solution.keys():
                if pred_name not in predicate_styling:
                    continue

                priority = predicate_styling[pred_name].get("priority", 0)
                predicates_to_render.append((pred_name, priority))

            # Sort by priority (higher priority rendered later, so they appear on top)
            predicates_to_render.sort(key=lambda x: x[1])

            # Process predicates in priority order
            for pred_name, _ in predicates_to_render:
                pred_instances = solution[pred_name]
                render_info = predicate_styling.get(pred_name, {})

                # Get default symbol and color (used if no custom renderer)
                default_symbol = render_info.get("symbol", pred_name[0])
                default_color = render_info.get("color", None)
                default_background = render_info.get("background", None)

                # Check if this predicate has a custom renderer
                custom_renderer = render_info.get("custom_renderer")

                # Process each predicate instance
                # Process each predicate instance
                for pred in pred_instances:
                    # Get render items - either from custom renderer or create a default one
                    if custom_renderer:
                        # Use custom renderer function that returns RenderItem objects
                        render_items = custom_renderer(pred)
                    else:
                        # Create a single RenderItem with default values
                        render_items = [
                            RenderItem(
                                loc=pred["loc"],
                                symbol=default_symbol,
                                color=default_color,
                                background=default_background,
                            )
                        ]

                    # Process all render items uniformly
                    for item in render_items:
                        # Extract row/col from the location predicate
                        loc = item.loc
                        row = loc["row"].value
                        col = loc["col"].value

                        # Adjust for 1-based indexing
                        grid_row = row - 1
                        grid_col = col - 1

                        if grid_row < 0 or grid_row >= self.rows or grid_col < 0 or grid_col >= self.cols:
                            continue

                        # Get current cell content for preservation
                        current_symbol, current_fg, current_bg = grid[grid_row][grid_col]

                        # Use or operator to handle preservation
                        grid[grid_row][grid_col] = (
                            item.symbol or current_symbol,
                            item.color or current_fg,
                            item.background or current_bg,
                        )

        # Convert grid to string
        rows = []
        join_char = render_config.get("join_char", " ")
        for row_in_grid in grid:
            row_str = []
            for char, color, background in row_in_grid:
                if use_colors:
                    row_str.append(colorize(char, color, background))
                else:
                    row_str.append(char)

            rows.append(join_char.join(row_str))

        return "\n".join(rows)
