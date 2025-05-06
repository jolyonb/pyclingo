from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeAlias

from aspuzzle.puzzle import Module, Puzzle, cached_predicate
from pyclingo import ANY, Predicate, Variable

GridCellData: TypeAlias = tuple[int, int, int | str]


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
    def parse_grid(self, grid_data: list[str], map_to_integers: bool = False) -> list[GridCellData]:
        """
        Parse the grid data into a structured format.

        Args:
            grid_data: The raw grid data as a list of strings
            map_to_integers: Whether to convert symbols to unique integers

        Returns:
            List of (row, col, value) tuples for non-empty cells
        """
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
    @abstractmethod
    def Direction(self) -> type[Predicate]:
        """Get the Direction predicate for this grid, defining all possible directions as vectors."""

    @property
    @cached_predicate
    def Directions(self) -> type[Predicate]:
        """Get the Directions predicate, identifying all directions."""
        Directions = Predicate.define("directions", ["name"], namespace=self.namespace, show=False)

        self.section("All directions")

        # Define Directions for each direction vector
        N = Variable("N")
        self.when(self.Direction(name=N, vector=ANY), Directions(name=N))

        return Directions

    @property
    @abstractmethod
    def OrthogonalDirections(self) -> type[Predicate]:
        """Get the OrthogonalDirections predicate, identifying orthogonal direction."""

    @property
    @abstractmethod
    def Orthogonal(self) -> type[Predicate]:
        """Get the orthogonal adjacency predicate (cells that share an edge)."""

    @property
    @abstractmethod
    def VertexSharing(self) -> type[Predicate]:
        """Get the vertex-sharing adjacency predicate."""

    @property
    @abstractmethod
    def Line(self) -> type[Predicate]:
        """Get the Line predicate defining major lines in the grid."""

    @abstractmethod
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

    @abstractmethod
    def cell(self, suffix: str = "") -> Predicate:
        """Get a cell predicate for this grid with variable values."""
        pass
