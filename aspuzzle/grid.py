from typing import Any

from aspuzzle.puzzle import Module, Puzzle, cached_predicate
from pyclingo import ExplicitPool, Min, Not, Predicate, RangePool, create_variables
from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.value import ANY, SymbolicConstant, Variable


class Grid(Module):
    """Module for grid-based puzzles with rows and columns. Note that this uses 1-based indexing!"""

    def __init__(
        self,
        puzzle: Puzzle,
        rows: int | SymbolicConstant,
        cols: int | SymbolicConstant,
        name: str = "grid",
        primary_namespace: bool = True,
    ):
        """Initialize a grid module with specified dimensions."""
        super().__init__(puzzle, name, primary_namespace)

        self.rows = rows
        self.cols = cols
        self._has_outside_border: bool = False

    @cached_predicate
    def Cell(self) -> type[Predicate]:
        """Get the Cell predicate for this grid."""
        Cell = Predicate.define("cell", ["row", "col"], namespace=self.namespace, show=False)
        self._Cell = Cell  # To avoid circular definitions with Outside

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

    def cell(self, suffix: str = "") -> Predicate:
        """Get a cell predicate for this grid with variable values."""
        if suffix:
            suffix = f"_{suffix}"
        R, C = create_variables(f"R{suffix}", f"C{suffix}")
        return self.Cell(row=R, col=C)

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

    def outside_grid(self, suffix: str = "") -> Predicate:
        """Get an outside_grid predicate for this grid with variable values."""
        return self.OutsideGrid(self.cell(suffix=suffix))

    @cached_predicate
    def Direction(self) -> type[Predicate]:
        """Get the Direction predicate for this grid, defining all possible directions as vectors."""
        Direction = Predicate.define("direction", ["name", "vector"], namespace=self.namespace, show=False)

        self.section("Define directions in the grid")

        # Define the 8 cardinal and intercardinal directions
        directions = [
            ("n", -1, 0),
            ("ne", -1, 1),
            ("e", 0, 1),
            ("se", 1, 1),
            ("s", 1, 0),
            ("sw", 1, -1),
            ("w", 0, -1),
            ("nw", -1, -1),
        ]

        self.fact(*[Direction(name=name, vector=self.Cell(row=dr, col=dc)) for name, dr, dc in directions])

        return Direction

    @cached_predicate
    def Directions(self) -> type[Predicate]:
        """Get the Directions predicate, identifying all directions."""
        Directions = Predicate.define("directions", ["name"], namespace=self.namespace, show=False)

        self.section("All directions")

        # Define Directions for each direction vector
        N = Variable("N")
        self.when(self.Direction(name=N, vector=ANY), Directions(name=N))

        return Directions

    @cached_predicate
    def OrthogonalDirections(self) -> type[Predicate]:
        """Get the OrthogonalDirections predicate, identifying orthogonal directions (N,S,E,W)."""
        OrthogonalDirections = Predicate.define("orthogonal_directions", ["name"], namespace=self.namespace, show=False)

        self.section("Orthogonal directions")

        # Define the 4 orthogonal directions
        orthogonal_dirs = ["n", "e", "s", "w"]
        self.fact(OrthogonalDirections(ExplicitPool(orthogonal_dirs)))

        return OrthogonalDirections

    def direction(self, name_suffix: str = "", vector_suffix: str = "vec") -> Predicate:
        """Get a direction predicate including names and vectors."""
        if name_suffix:
            name_suffix = f"_{name_suffix}"

        N = Variable(f"N{name_suffix}")
        return self.Direction(name=N, vector=self.cell(suffix=vector_suffix))

    def directions(self, name_suffix: str = "") -> Predicate:
        """Get an orthogonal direction predicate, listing the names of all directions."""
        if name_suffix:
            name_suffix = f"_{name_suffix}"

        N = Variable(f"N{name_suffix}")
        return self.Directions(name=N)

    def orthogonal_directions(self, name_suffix: str = "") -> Predicate:
        """Get an orthogonal direction predicate, listing the names of orthogonal directions."""
        if name_suffix:
            name_suffix = f"_{name_suffix}"

        N = Variable(f"N{name_suffix}")
        return self.OrthogonalDirections(name=N)

    @cached_predicate
    def Orthogonal(self) -> type[Predicate]:
        """Get the orthogonal adjacency predicate (cells that share an edge)."""
        Orthogonal = Predicate.define("orthogonal", ["cell1", "cell2"], namespace=self.namespace, show=False)

        R, C = create_variables("R", "C")
        Dir, DR, DC = create_variables("Dir", "DR", "DC")
        cell = self.Cell(row=R, col=C)
        adj_cell = self.Cell(row=R + DR, col=C + DC)

        # Initialize predicates that we'll need
        _ = self.Direction
        _ = self.OrthogonalDirections

        self.section("Orthogonal adjacency definition")

        # Define cells that share an edge (orthogonally adjacent)
        self.when(
            [
                cell,
                self.OrthogonalDirections(Dir),
                self.Direction(Dir, vector=self.Cell(row=DR, col=DC)),
                adj_cell,
            ],
            Orthogonal(cell1=cell, cell2=adj_cell),
        )

        return Orthogonal

    def orthogonal(self, suffix_1: str = "", suffix_2: str = "adj") -> Predicate:
        """Get the orthogonal adjacency predicate with variable values."""
        return self.Orthogonal(cell1=self.cell(suffix_1), cell2=self.cell(suffix_2))

    @cached_predicate
    def VertexSharing(self) -> type[Predicate]:
        """Get the vertex-sharing adjacency predicate."""
        VertexSharing = Predicate.define("vertex_sharing", ["cell1", "cell2"], namespace=self.namespace, show=False)

        R, C = create_variables("R", "C")
        Dir, DR, DC = create_variables("Dir", "DR", "DC")
        cell = self.Cell(row=R, col=C)
        adj_cell = self.Cell(row=R + DR, col=C + DC)

        # Initialize predicates that we'll need
        _ = self.Direction

        self.section("Vertex-sharing adjacency definition")

        # Define cells that share a vertex
        self.when(
            [
                cell,
                self.Direction(ANY, vector=self.Cell(row=DR, col=DC)),
                adj_cell,
            ],
            VertexSharing(cell1=cell, cell2=adj_cell),
        )

        return VertexSharing

    def vertex_sharing(self, suffix_1: str = "", suffix_2: str = "adj") -> Predicate:
        """Get the vertex-sharing adjacency predicate with variable values."""
        return self.VertexSharing(cell1=self.cell(suffix_1), cell2=self.cell(suffix_2))

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

    def line(self, direction_suffix: str = "", index_suffix: str = "", loc_suffix: str = "") -> Predicate:
        """Get a line predicate for this grid with variable values."""
        if direction_suffix:
            direction_suffix = f"_{direction_suffix}"
        if index_suffix:
            index_suffix = f"_{index_suffix}"

        D = Variable(f"D{direction_suffix}")
        Idx = Variable(f"Idx{index_suffix}")
        return self.Line(direction=D, index=Idx, loc=self.cell(suffix=loc_suffix))

    @property
    def has_outside_border(self) -> bool:
        """Whether an outside border was included in the grid definition."""
        return self._has_outside_border

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


def do_not_show_outside(pred: Predicate, grid: Grid) -> None:
    """
    This helper function sets the show directive on a predicate to not display for cells outside the grid.
    The predicate must be instantiated with the grid.cell() location.
    """
    pred.__class__.set_show_directive(ConditionalLiteral(pred, [pred, Not(grid.outside_grid())]))
