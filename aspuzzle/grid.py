from aspuzzle.puzzle import Module, Puzzle, cached_predicate
from pyclingo import Not, Predicate, RangePool, create_variables
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
        include_outside_border: bool = False,
        primary_namespace: bool = True,
    ):
        """Initialize a grid module with specified dimensions."""
        super().__init__(puzzle, name, primary_namespace)

        self.rows = rows
        self.cols = cols
        self.include_outside_border = include_outside_border

    @cached_predicate
    def Cell(self) -> type[Predicate]:
        """Get the Cell predicate for this grid."""
        Cell = Predicate.define("cell", ["row", "col"], namespace=self.namespace, show=False)
        self._Cell = Cell  # To avoid circular definitions with Outside

        R, C = create_variables("R", "C")

        # Define grid cells
        self.section("Define cells in the grid")
        offset = 1 if self.include_outside_border else 0
        self.when(
            [
                R.in_(RangePool(1 - offset, self.rows + offset)),
                C.in_(RangePool(1 - offset, self.cols + offset)),
            ],
            Cell(R, C),
        )

        if self.include_outside_border:
            # Define the Outside predicate
            _ = self.Outside

        return Cell

    def cell(self, suffix: str = "") -> Predicate:
        """Get a cell predicate for this grid with variable values."""
        if suffix:
            suffix = f"_{suffix}"
        R, C = create_variables(f"R{suffix}", f"C{suffix}")
        return self.Cell(row=R, col=C)

    @cached_predicate
    def Outside(self) -> type[Predicate]:
        """Get the Outside predicate identifying cells in the outside border."""
        if not self.include_outside_border:
            raise ValueError("Grid does not include outside border")

        Outside = Predicate.define("outside", ["loc"], namespace=self.namespace, show=False)

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

        return Outside

    def outside(self, suffix: str = "") -> Predicate:
        """Get an outside predicate for this grid with variable values."""
        return self.Outside(self.cell(suffix=suffix))

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
    def OrthogonalDirection(self) -> type[Predicate]:
        """Get the OrthogonalDirection predicate, identifying orthogonal directions (N,S,E,W)."""
        OrthogonalDirection = Predicate.define("orthogonal_direction", ["name"], namespace=self.namespace, show=False)

        self.section("Orthogonal directions")

        # Define the 4 orthogonal directions
        orthogonal_dirs = ["n", "e", "s", "w"]
        self.fact(*[OrthogonalDirection(name=name) for name in orthogonal_dirs])

        return OrthogonalDirection

    def directions(self, name_suffix: str = "", vector_suffix: str = "vec") -> Predicate:
        """Get a direction predicate with variable values."""
        if name_suffix:
            name_suffix = f"_{name_suffix}"

        N = Variable(f"N{name_suffix}")

        return self.Direction(name=N, vector=self.cell(suffix=vector_suffix))

    def orthogonal_directions(self, name_suffix: str = "") -> Predicate:
        """Get an orthogonal direction predicate with variable values."""
        if name_suffix:
            name_suffix = f"_{name_suffix}"

        N = Variable(f"N{name_suffix}")
        return self.OrthogonalDirection(name=N)

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
        _ = self.OrthogonalDirection

        self.section("Orthogonal adjacency definition")

        # Define cells that share an edge (orthogonally adjacent)
        self.when(
            [
                cell,
                self.OrthogonalDirection(Dir),
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


def do_not_show_outside(pred: Predicate, grid: Grid) -> None:
    """
    This helper function sets the show directive on a predicate to not display for cells outside the grid.
    The predicate must be instantiated with the grid.cell() location.
    """
    pred.__class__.set_show_directive(ConditionalLiteral(pred, [pred, Not(grid.outside())]))
