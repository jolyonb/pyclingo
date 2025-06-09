from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeAlias

from aspuzzle.grids.rendering import RenderItem
from aspuzzle.puzzle import Module, Puzzle, cached_predicate
from pyclingo import ANY, ExplicitPool, Min, Predicate, Variable, create_variables
from pyclingo.conditional_literal import ConditionalLiteral

# Representing a location and a value
GridCellData: TypeAlias = tuple[tuple[int, ...], int | str]


class Grid(Module, ABC):
    """Abstract base class for all grid types in puzzles."""

    def __init__(
        self,
        puzzle: Puzzle,
        name: str = "grid",
        primary_namespace: bool = True,
    ):
        """Initialize a base grid module."""
        super().__init__(puzzle, name, primary_namespace)
        self._has_outside_border: bool = False

    @abstractmethod
    def with_new_puzzle(self, puzzle: Puzzle) -> Grid:
        """Return a copy of this Grid with a new puzzle."""

    @property
    def has_outside_border(self) -> bool:
        """Whether an outside border was included in the grid definition."""
        return self._has_outside_border

    @classmethod
    @abstractmethod
    def from_config(
        cls,
        puzzle: Puzzle,
        config: dict[str, Any],
        name: str = "grid",
        primary_namespace: bool = True,
    ) -> Grid:
        """Create a grid from configuration."""
        pass

    @abstractmethod
    def parse_grid(
        self, grid_data: list[str] | list[list[str | int]], map_to_integers: bool = False
    ) -> list[GridCellData]:
        """
        Parse the grid data into a structured format.

        Args:
            grid_data: The raw grid data as a list of strings, or a list of lists of integers or strings
            map_to_integers: Whether to convert symbols to unique integers

        Returns:
            List of (loc, value) tuples for non-empty cells
        """
        pass

    @property
    @abstractmethod
    def cell_fields(self) -> list[str]:
        """Returns the list of field names associated with the Cell predicate for this grid"""

    @property
    @abstractmethod
    def cell_var_names(self) -> list[str]:
        """Returns the default list of variable names for the Cell predicate for this grid"""

    @property
    @abstractmethod
    def direction_vectors(self) -> list[tuple[str, tuple[int, ...]]]:
        """Returns the list of directions and vectors for this grid"""

    @property
    @abstractmethod
    def opposite_directions(self) -> list[tuple[str, str]]:
        """Returns the list of opposite direction names for this grid"""

    @property
    @abstractmethod
    def orthogonal_direction_names(self) -> list[str]:
        """Returns the list of orthogonal direction names for this grid"""

    @property
    @abstractmethod
    def line_direction_names(self) -> list[str]:
        """Returns the list of line direction names for this grid"""

    @property
    @abstractmethod
    def line_direction_descriptions(self) -> dict[str, str]:
        """Returns human-readable descriptions of line directions"""
        pass

    @property
    @abstractmethod
    def line_characters(self) -> dict[str, str]:
        """Get ASCII line characters for direction combination."""
        pass

    @abstractmethod
    def get_line_count(self, direction: str) -> int:
        """Returns the number of lines in the specified direction"""
        pass

    @property
    @abstractmethod
    def Cell(self) -> type[Predicate]:
        """Get the Cell predicate for this grid."""

    @property
    @abstractmethod
    def OutsideGrid(self) -> type[Predicate]:
        """Get the OutsideGrid predicate identifying cells in the outside border."""

    @property
    @cached_predicate
    def Direction(self) -> type[Predicate]:
        """Get the Direction predicate for this grid, defining all possible directions as vectors."""
        Direction = Predicate.define("direction", ["name", "vector"], namespace=self.namespace, show=False)

        self.section("Define directions in the grid")

        direction_facts = []
        for name, coords in self.direction_vectors:
            cell_args = dict(zip(self.cell_fields, coords))
            direction_facts.append(Direction(name=name, vector=self.Cell(**cell_args)))

        self.fact(*direction_facts)

        return Direction

    @property
    @cached_predicate
    def Directions(self) -> type[Predicate]:
        """Get the Directions predicate, identifying all directions."""
        Directions = Predicate.define("directions", ["name"], namespace=self.namespace, show=False)
        self.section("All directions")
        N = Variable("N")
        self.when(self.Direction(name=N, vector=ANY), Directions(name=N))
        return Directions

    @property
    @cached_predicate
    def Opposite(self) -> type[Predicate]:
        """Get the Opposite predicate, which identifies which directions are opposites."""
        Opposite = Predicate.define("opposite", ["direction1", "direction2"], namespace=self.namespace, show=False)
        self.section("Opposite directions")
        for dir1, dir2 in self.opposite_directions:
            self.fact(Opposite(dir1, dir2))
        return Opposite

    @property
    @cached_predicate
    def OrthogonalDirections(self) -> type[Predicate]:
        """Get the OrthogonalDirections predicate, identifying orthogonal directions."""
        OrthogonalDirections = Predicate.define("orthogonal_directions", ["name"], namespace=self.namespace, show=False)
        self.section("Orthogonal directions")
        self.fact(OrthogonalDirections(ExplicitPool(self.orthogonal_direction_names)))
        return OrthogonalDirections

    @property
    @cached_predicate
    def Orthogonal(self) -> type[Predicate]:
        """Get the orthogonal adjacency predicate (cells that share an edge)."""
        Orthogonal = Predicate.define("orthogonal", ["cell1", "cell2"], namespace=self.namespace, show=False)

        D = create_variables("D")
        cell = self.cell()
        vector = self.cell(suffix="vec")
        cell_plus_vector = self.add_vector_to_cell(cell, vector)

        # Initialize predicates that we'll need
        _ = self.Direction
        _ = self.OrthogonalDirections

        self.section("Orthogonal adjacency definition")

        # Define cells that share an edge (orthogonally adjacent)
        self.when(
            [
                cell,
                self.OrthogonalDirections(D),
                self.Direction(D, vector=vector),
                cell_plus_vector,
            ],
            Orthogonal(cell1=cell, cell2=cell_plus_vector),
        )

        return Orthogonal

    @property
    @cached_predicate
    def OrthogonalDir(self) -> type[Predicate]:
        """Get the orthogonal adjacency + direction predicate (cells that share an edge)."""
        OrthogonalDir = Predicate.define(
            "orthogonal_dir", ["cell1", "direction", "cell2"], namespace=self.namespace, show=False
        )

        D = create_variables("D")
        cell = self.cell()
        vector = self.cell(suffix="vec")
        cell_plus_vector = self.add_vector_to_cell(cell, vector)

        # Initialize predicates that we'll need
        _ = self.Direction
        _ = self.OrthogonalDirections

        self.section("Orthogonal adjacency with direction definition")

        self.when(
            [
                cell,
                self.OrthogonalDirections(D),
                self.Direction(D, vector=vector),
                cell_plus_vector,
            ],
            OrthogonalDir(cell1=cell, direction=D, cell2=cell_plus_vector),
        )

        return OrthogonalDir

    @property
    @cached_predicate
    def VertexSharing(self) -> type[Predicate]:
        """Get the vertex-sharing adjacency predicate."""
        VertexSharing = Predicate.define("vertex_sharing", ["cell1", "cell2"], namespace=self.namespace, show=False)

        cell = self.cell()
        vector = self.cell(suffix="vec")
        cell_plus_vector = self.add_vector_to_cell(cell, vector)

        # Initialize predicates that we'll need
        _ = self.Direction

        self.section("Vertex-sharing adjacency definition")

        # Define cells that share a vertex
        self.when(
            [
                cell,
                self.Direction(ANY, vector=vector),
                cell_plus_vector,
            ],
            VertexSharing(cell1=cell, cell2=cell_plus_vector),
        )

        return VertexSharing

    @property
    @abstractmethod
    def Line(self) -> type[Predicate]:
        """Get the Line predicate defining major lines in the grid."""

    @property
    @abstractmethod
    def LineOfSight(self) -> type[Predicate]:
        """Get the LineOfSight predicate defining major lines in the grid, with position indexing."""

    def find_anchor_cell(
        self,
        condition_predicate: type[Predicate],
        cell_field: str,
        anchor_name: str,
        condition_fields: dict[str, Any] | None = None,
        anchor_fields: list[str] | None = None,
        segment: str | None = None,
    ) -> type[Predicate]:
        """
        Find the lexicographically minimum cell that satisfies the given condition.

        Args:
            condition_predicate: The predicate class to check
            cell_field: The name of the field that contains the cell location
            anchor_name: Name for the anchor predicate
            condition_fields: Dictionary of field names to values to include in the condition predicate
            anchor_fields: List of field names from condition_fields to include in the anchor predicate
            segment: Segment to publish these rules to

        Returns:
            The anchor predicate class that marks the anchor cell

        Example:
            ```
            # Find anchor for white cells with specific value
            anchor = grid.find_anchor_cell(
                condition_predicate=WhiteCell,
                cell_field="loc",
                anchor_name="white_anchor",
                condition_fields={"value": 5},  # Only white cells with value=5
                anchor_fields=["value"]         # Include value in anchor predicate
            )
            # Creates: white_anchor(loc=min_cell, value=5)
            ```
        """
        self.puzzle.section(f"Find anchor cell for {condition_predicate.__name__}", segment=segment)

        if condition_fields is None:
            condition_fields = {}
        if anchor_fields is None:
            anchor_fields = []

        # Validate that anchor_fields are actually in condition_fields
        for field in anchor_fields:
            if field not in condition_fields:
                raise ValueError(f"Anchor field '{field}' not found in condition_fields")

        # Define the anchor predicate
        AnchorPred = Predicate.define(anchor_name, [cell_field] + anchor_fields, namespace=self.namespace, show=False)

        # Construct the anchor cell
        Cmin, Cell = create_variables("Cmin", "Cell")
        self.puzzle.when(
            [
                Cmin == Min(Cell, condition=condition_predicate(**{cell_field: Cell}, **condition_fields)),
            ],
            AnchorPred(**{cell_field: Cmin}, **{k: v for k, v in condition_fields.items() if k in anchor_fields}),
            segment=segment,
        )

        return AnchorPred

    def cell(self, suffix: str = "") -> Predicate:
        """Get a cell predicate for this grid with variable values."""
        if suffix:
            suffix = f"_{suffix}"
        variables = create_variables(*[f"{var_name}{suffix}" for var_name in self.cell_var_names])
        cell_args = dict(zip(self.cell_fields, variables))
        return self.Cell(**cell_args)

    def outside_grid(self, suffix: str = "") -> Predicate:
        """Get an outside_grid predicate for this grid with variable values."""
        return self.OutsideGrid(self.cell(suffix=suffix))

    def direction(self, name_suffix: str = "", vector_suffix: str = "vec") -> Predicate:
        """Get a direction predicate including names and vectors."""
        if name_suffix:
            name_suffix = f"_{name_suffix}"
        N = Variable(f"N{name_suffix}")
        return self.Direction(name=N, vector=self.cell(suffix=vector_suffix))

    def directions(self, name_suffix: str = "") -> Predicate:
        """Get a direction predicate, listing the names of all directions."""
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

    def orthogonal(self, suffix_1: str = "", suffix_2: str = "adj") -> Predicate:
        """Get the orthogonal adjacency predicate with variable values."""
        return self.Orthogonal(cell1=self.cell(suffix_1), cell2=self.cell(suffix_2))

    def vertex_sharing(self, suffix_1: str = "", suffix_2: str = "adj") -> Predicate:
        """Get the vertex-sharing adjacency predicate with variable values."""
        return self.VertexSharing(cell1=self.cell(suffix_1), cell2=self.cell(suffix_2))

    def line(self, direction_suffix: str = "", index_suffix: str = "", loc_suffix: str = "") -> Predicate:
        """Get a line predicate for this grid with variable values."""
        if direction_suffix:
            direction_suffix = f"_{direction_suffix}"
        if index_suffix:
            index_suffix = f"_{index_suffix}"

        D = Variable(f"D{direction_suffix}")
        Idx = Variable(f"Idx{index_suffix}")
        return self.Line(direction=D, index=Idx, loc=self.cell(suffix=loc_suffix))

    @abstractmethod
    def add_vector_to_cell(self, cell_pred: Predicate, vector_pred: Predicate) -> Predicate:
        """
        Add a vector to a cell, returning the new cell location.

        Args:
            cell_pred: The starting cell predicate
            vector_pred: The vector predicate (as defined in Direction)

        Returns:
            A new Cell predicate with the vector added
        """

    @abstractmethod
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
        pass


def do_not_show_outside(pred: Predicate, grid: Grid) -> None:
    """
    This helper function sets the show directive on a predicate to not display for cells outside the grid.
    The predicate must be instantiated with the grid.cell() location.
    """
    pred.__class__.set_show_directive(ConditionalLiteral(pred, [pred, ~grid.outside_grid()]))
