from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeAlias

from aspuzzle.puzzle import Module, Puzzle
from pyclingo import Predicate

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

    @abstractmethod
    def cell(self, suffix: str = "") -> Predicate:
        """Get a cell predicate for this grid with variable values."""
        pass

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
