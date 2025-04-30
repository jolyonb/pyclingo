from aspuzzle.puzzle import Module, Puzzle, cached_predicate
from pyclingo import Equals, Predicate, RangePool, create_variables, ExplicitPool
from pyclingo.value import SymbolicConstant, Variable


class Grid(Module):
    """Module for grid-based puzzles with rows and columns."""

    def __init__(
        self,
        puzzle: Puzzle,
        rows: int | SymbolicConstant,
        cols: int | SymbolicConstant,
        name: str = "grid",
    ):
        """Initialize a grid module with specified dimensions."""
        super().__init__(puzzle, name)

        self.rows = rows
        self.cols = cols

    @cached_predicate
    def Cell(self) -> type[Predicate]:
        """Get the Cell predicate for this grid."""
        Cell = Predicate.define("cell", ["row", "col"], namespace=self.name, show=False)

        R, C = create_variables("R", "C")

        # Define grid cells
        self.section("Grid definition")
        self.when(
            [R.in_(RangePool(0, self.rows - 1)), C.in_(RangePool(0, self.cols - 1))],
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
    def Direction(self) -> type[Predicate]:
        """Get the Direction predicate for this grid, defining all possible directions as vectors."""
        Direction = Predicate.define(
            "direction", ["name", "vector"], namespace=self.name, show=False
        )

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

        self.fact(
            *[
                Direction(name=name, vector=self.Cell(row=dr, col=dc))
                for name, dr, dc in directions
            ]
        )

        return Direction

    @cached_predicate
    def OrthogonalDirection(self) -> type[Predicate]:
        """Get the OrthogonalDirection predicate, identifying orthogonal directions (N,S,E,W)."""
        OrthogonalDirection = Predicate.define(
            "orthogonal_direction", ["name"], namespace=self.name, show=False
        )

        self.section("Orthogonal direction definition")

        # Define the 4 orthogonal directions
        orthogonal_dirs = ["n", "e", "s", "w"]
        self.fact(*[OrthogonalDirection(name=name) for name in orthogonal_dirs])

        return OrthogonalDirection

    @cached_predicate
    def VertexSharingDirection(self) -> type[Predicate]:
        """Get the VertexSharingDirection predicate, identifying all 8 directions."""
        VertexSharingDirection = Predicate.define(
            "vertex_sharing_direction", ["name"], namespace=self.name, show=False
        )

        self.section("Vertex sharing direction definition")

        # All 8 directions are vertex-sharing
        vertex_dirs = ["n", "ne", "e", "se", "s", "sw", "w", "nw"]
        self.fact(VertexSharingDirection(ExplicitPool(vertex_dirs)))

        return VertexSharingDirection

    def directions(
        self, name_suffix: str = "", vector_suffix: str = "vec"
    ) -> Predicate:
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

    def vertex_sharing_directions(self, name_suffix: str = "") -> Predicate:
        """Get a vertex-sharing direction predicate with variable values."""
        if name_suffix:
            name_suffix = f"_{name_suffix}"

        N = create_variables(f"N{name_suffix}")[0]
        return self.VertexSharingDirection(name=N)

    @cached_predicate
    def Orthogonal(self) -> type[Predicate]:
        """Get the orthogonal adjacency predicate (cells that share an edge)."""
        Orthogonal = Predicate.define(
            "orthogonal", ["cell1", "cell2"], namespace=self.name, show=False
        )

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
        """Get the vertex-sharing adjacency predicate (cells that share at least a vertex)."""
        VertexSharing = Predicate.define(
            "vertex_sharing", ["cell1", "cell2"], namespace=self.name, show=False
        )

        R, C = create_variables("R", "C")
        Dir, DR, DC = create_variables("Dir", "DR", "DC")
        cell = self.Cell(row=R, col=C)
        adj_cell = self.Cell(row=R + DR, col=C + DC)

        # Initialize predicates that we'll need
        _ = self.Direction
        _ = self.VertexSharingDirection

        self.section("Vertex-sharing adjacency definition")

        # Define cells that share a vertex
        self.when(
            [
                cell,
                self.VertexSharingDirection(Dir),
                self.Direction(Dir, vector=self.Cell(row=DR, col=DC)),
                adj_cell,
            ],
            VertexSharing(cell1=cell, cell2=adj_cell),
        )

        return VertexSharing

    def vertex_sharing(self, suffix_1: str = "", suffix_2: str = "adj") -> Predicate:
        """Get the vertex-sharing adjacency predicate with variable values."""
        return self.VertexSharing(cell1=self.cell(suffix_1), cell2=self.cell(suffix_2))
