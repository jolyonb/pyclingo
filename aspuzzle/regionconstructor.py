from __future__ import annotations

from typing import Any

from aspuzzle.grids.base import Grid
from aspuzzle.puzzle import Module, Puzzle, cached_predicate
from pyclingo import ANY, Choice, Count, Not, Predicate, create_variables
from pyclingo.term import Term


class RegionConstructor(Module):
    """
    Module for constructing regions in grid-based puzzles.

    This module provides functionality to create and manage regions within a grid,
    supporting both fixed-anchor approaches (e.g., Nurikabe) and dynamic-anchor
    approaches (e.g., Fillomino).
    """

    def __init__(
        self,
        puzzle: Puzzle,
        grid: Grid,
        name: str = "regions",
        primary_namespace: bool = True,
        anchor_predicate: type[Predicate] | None = None,
        anchor_fields: dict[str, Any] | None = None,
        allow_regionless: bool = True,
    ):
        """
        Initialize a RegionConstructor module.

        Args:
            puzzle: The puzzle this module belongs to
            grid: The grid this region constructor operates on
            name: The name of this module (used for the segment)
            primary_namespace: If True, don't add namespace prefixes
            anchor_predicate: Optional predicate defining fixed anchors for regions
                              If None, flexible anchors will be used
            anchor_fields: Optional dictionary of field names to values for filtering specific anchors
            allow_regionless: If True, cells can be outside any region
                            If False, all cells must belong to a region
        """
        super().__init__(puzzle, name, primary_namespace)
        self.grid = grid
        self._anchor_predicate = anchor_predicate
        self._anchor_fields = anchor_fields or {}
        self._dynamic_anchors = anchor_predicate is None
        self._allow_regionless = allow_regionless

    @property
    def dynamic_anchors(self) -> bool:
        """Whether this region constructor uses dynamic anchors."""
        return self._dynamic_anchors

    @property
    def allow_regionless(self) -> bool:
        """Whether this region constructor allows cells to be outside any region."""
        return self._allow_regionless

    @property
    @cached_predicate
    def Regionless(self) -> type[Predicate]:
        """
        Get the Regionless predicate defining cells not in any region.

        Raises:
            ValueError: If allow_regionless is False (all cells must be in a region)
        """
        if not self.allow_regionless:
            raise ValueError("Cannot use Regionless predicate when allow_regionless is False")

        return Predicate.define("regionless", ["loc"], namespace=self.namespace, show=False)

    @property
    @cached_predicate
    def Anchor(self) -> type[Predicate]:
        """Get the Anchor predicate defining the cells that anchor regions."""
        return Predicate.define("anchor", ["loc"], namespace=self.namespace, show=False)

    @property
    @cached_predicate
    def Connected(self) -> type[Predicate]:
        """Get the Connected predicate defining cells that are connected to regions."""
        return Predicate.define("connected", ["loc"], namespace=self.namespace, show=False)

    @property
    @cached_predicate
    def Region(self) -> type[Predicate]:
        """Get the Region predicate defining which cells belong to which regions."""
        return Predicate.define("region", ["loc", "anchor"], namespace=self.namespace, show=True)

    @property
    @cached_predicate
    def ConnectsTo(self) -> type[Predicate]:
        """Get the ConnectsTo predicate defining connections between cells in a region."""
        return Predicate.define("connects_to", ["loc1", "loc2"], namespace=self.namespace, show=False)

    @property
    @cached_predicate
    def RegionSize(self) -> type[Predicate]:
        """Get the RegionSize predicate defining the size of each region."""
        RegionSize = Predicate.define("region_size", ["anchor", "size"], namespace=self.namespace, show=True)

        # Generate the region size calculation rules
        self.section("Region Size Calculation")

        AnchorCell, Cell, Size = create_variables("Anchor", "Cell", "Size")

        # Count cells in each region
        self.when(
            [
                self.Anchor(loc=AnchorCell),
                Size == Count(Cell, condition=self.Region(loc=Cell, anchor=AnchorCell)),
            ],
            let=RegionSize(anchor=AnchorCell, size=Size),
        )

        return RegionSize

    def finalize(self) -> None:
        """
        Called just before rendering in case the module needs to add any rules based on an internal state.
        """
        # We need access to grid.has_outside_border, which we can only do in finalize
        self._construct_rules()

    def _construct_rules(self) -> None:
        """Generate all rules for region construction."""
        # Variables we'll need
        C, N, A, A1, A2 = create_variables("C", "N", "A", "A1", "A2")
        cell = self.grid.cell()

        # Section 1: Cell Status Assignment
        self.section("Cell Status Assignment")

        # Create a choice rule for cell status assignment
        choice = Choice(self.Connected(loc=cell))
        if self.allow_regionless:
            choice.add(self.Regionless(loc=cell))
        if self.dynamic_anchors:
            choice.add(self.Anchor(loc=cell))
        choice.exactly(1)
        # Apply the choice rule for each valid cell
        conditions: list[Term] = [cell]
        if self.grid.has_outside_border:
            conditions.append(Not(self.grid.outside_grid()))

        self.when(conditions, let=choice)

        # For fixed anchors, we need to identify the anchor locations
        if not self.dynamic_anchors:
            # Define anchors based on the provided predicate
            assert self._anchor_predicate is not None
            anchor_args = {**self._anchor_fields, "loc": C}
            anchor_conditions: list[Term] = [self._anchor_predicate(**anchor_args)]
            if self.grid.has_outside_border:
                anchor_conditions.append(Not(self.grid.OutsideGrid(loc=C)))
            self.when(anchor_conditions, let=self.Anchor(loc=C))

            # Anchor cells are connected
            self.when(self.Anchor(loc=C), let=self.Connected(loc=C))

        # Section 2: Connection Rules
        self.section("Connection Rules")

        # Connected cells can connect to other orthogonal cells
        choice_conditions: list[Term] = [self.grid.Orthogonal(cell1=C, cell2=N)]
        if self.allow_regionless:
            choice_conditions.append(Not(self.Regionless(loc=N)))
        choice = Choice(self.ConnectsTo(loc1=C, loc2=N))
        if self.dynamic_anchors:
            # Dynamic anchors: connected cells must have at least one connection (as they're not anchors)
            choice.at_least(1)
            # For fixed anchors, no minimum constraint is needed, as connected cells can also be anchors
        self.when(self.Connected(loc=C), let=choice)

        # Connections are symmetric (bidirectional)
        self.when(self.ConnectsTo(loc1=C, loc2=N), let=self.ConnectsTo(loc1=N, loc2=C))

        # Section 3: Region Propagation
        self.section("Region Propagation")
        # Anchors define their own region
        self.when(self.Anchor(loc=C), let=self.Region(loc=C, anchor=C))
        # Regions propagate through connections
        self.when([self.ConnectsTo(loc1=N, loc2=C), self.Region(loc=C, anchor=A)], let=self.Region(loc=N, anchor=A))
        # Orthogonal cells in the same region must be connected
        self.when(
            [self.grid.Orthogonal(cell1=C, cell2=N), self.Region(loc=C, anchor=A), self.Region(loc=N, anchor=A)],
            let=self.ConnectsTo(loc1=C, loc2=N),
        )

        # Section 4: Integrity Constraints
        self.section("Integrity Constraints")

        if not self.dynamic_anchors:
            # These constraints enforce a single region per cell, but do so more cheaply than using a count aggregate
            # Connected cells must have at least one anchor
            self.forbid(self.Connected(loc=C), Not(self.Region(loc=C, anchor=ANY)))
            # Cells cannot belong to multiple different regions
            self.when(
                [self.Region(loc=C, anchor=A1), self.Region(loc=C, anchor=A2)],
                let=(A1 == A2),
            )
        else:
            # Dynamic anchors. This can lead to a complexity explosion, so we use #count aggregates instead of the
            # local rules.
            # All cells must have exactly one anchor
            conditions = [cell, C == Count(A, condition=self.Region(loc=cell, anchor=A))]
            if self.allow_regionless:
                conditions.append(Not(self.Regionless(loc=cell)))
            self.when(conditions, let=(C == 1))

            # Anchor must be the lexicographically smallest cell in its region
            self.forbid(self.Anchor(loc=C), self.Region(loc=N, anchor=C), N < C)
            # TODO: if this works, then finding an anchor cell in Grid is probably a lot easier than what I'm
            #       currently doing!
