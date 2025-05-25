from typing import Any, TypeVar

from aspuzzle.grids.base import Grid
from aspuzzle.grids.rendering import BgColor
from aspuzzle.puzzle import Puzzle
from pyclingo import ANY, Choice, Predicate, create_variables

T = TypeVar("T")  # For region ID type


class RegionColoring:
    """A lightweight utility for coloring regions using ASP."""

    def __init__(self, grid: Grid):
        """Initialize the region coloring utility.

        Args:
            grid: The grid containing the regions
        """
        self._puzzle = Puzzle(name="RegionColoring")
        self.grid = grid.with_new_puzzle(self._puzzle)

    def color_regions(self, regions: dict[T, list[tuple[int, ...]]], color_palette: list[BgColor]) -> dict[T, BgColor]:
        """
        Color regions using ASP to ensure no adjacent regions share colors.

        Args:
            regions: Dict mapping region IDs to lists of cell locations (as tuples)
            color_palette: List of background colors to use (must have at least 4 colors)

        Returns:
            Dictionary mapping region IDs to background colors

        Raises:
            ValueError: If the color palette has fewer than 4 colors
        """
        if not regions:
            return {}

        if len(color_palette) < 4:
            raise ValueError(
                f"Color palette must have at least 4 colors (Four Color Theorem), "
                f"but only {len(color_palette)} provided"
            )

        # Use the full palette - ASP will use only as many colors as needed
        result = self._try_coloring(regions, color_palette)

        # This should never happen with 4+ colors on a planar graph
        if result is None:
            raise RuntimeError(
                f"Failed to color regions with {len(color_palette)} colors. "
                "This violates the Four Color Theorem - please report this as a bug!"
            )

        return result

    def color_regions_from_predicate(
        self, region_instances: list[Predicate], id_field: str, loc_field: str, color_palette: list[BgColor]
    ) -> dict[Any, BgColor]:
        """
        Color regions defined by predicate instances.

        Args:
            region_instances: List of predicate instances defining regions
            id_field: Name of the field containing region ID
            loc_field: Name of the field containing cell location
            color_palette: List of background colors to use (must have at least 4 colors)

        Returns:
            Dictionary mapping region IDs to background colors
        """
        # Group by region ID
        regions: dict[Any, list[tuple[int, ...]]] = {}
        for instance in region_instances:
            region_id = instance[id_field].value
            loc = instance[loc_field]
            # Extract location as tuple
            loc_tuple = tuple(loc[field].value for field in self.grid.cell_fields)

            if region_id not in regions:
                regions[region_id] = []
            regions[region_id].append(loc_tuple)

        return self.color_regions(regions, color_palette)

    def _try_coloring(self, regions: dict[T, list[tuple[int, ...]]], colors: list[BgColor]) -> dict[T, BgColor] | None:
        """
        Try to color regions with a specific number of colors.

        Returns:
            Color mapping if successful, None if impossible
        """
        puzzle = self._puzzle

        # Define predicates
        Region = Predicate.define("region", ["loc", "id"], show=False)
        Adjacent = Predicate.define("adjacent", ["id1", "id2"], show=False)
        RegionColor = Predicate.define("region_color", ["id", "color_id"], show=True)

        # Add region facts
        for region_id, cells in regions.items():
            for cell_tuple in cells:
                cell_args = dict(zip(self.grid.cell_fields, cell_tuple))
                assert isinstance(region_id, (int, str))
                puzzle.fact(Region(loc=self.grid.Cell(**cell_args), id=region_id))

        # Define adjacency
        R1, R2, C1, C2, C = create_variables("R1", "R2", "C1", "C2", "C")
        puzzle.when(
            [
                Region(loc=C1, id=R1),
                Region(loc=C2, id=R2),
                self.grid.Orthogonal(cell1=C1, cell2=C2),
                R1 != R2,
            ],
            let=Adjacent(id1=R1, id2=R2),
        )

        # Color assignment
        R = create_variables("R")
        puzzle.when(
            Region(loc=ANY, id=R),
            let=Choice(
                element=RegionColor(id=R, color_id=C),
                condition=C.in_(range(len(colors))),
            ).exactly(1),
        )

        # Adjacency constraint
        puzzle.forbid(Adjacent(id1=R1, id2=R2), RegionColor(id=R1, color_id=C), RegionColor(id=R2, color_id=C))

        # Solve
        solutions = list(puzzle.solve(models=1))
        if not solutions:
            return None

        # print(f"Found region coloring solution in {puzzle.statistics['total_time']:0.2f}s")

        # Extract color assignments
        result = {}
        for pred_name, instances in solutions[0].items():
            if pred_name == "region_color":
                for instance in instances:
                    region_id = instance["id"].value
                    color_idx = instance["color_id"].value
                    result[region_id] = colors[color_idx]

        return result


DEFAULT_PALETTE = [
    BgColor.BLUE,
    BgColor.GREEN,
    BgColor.RED,
    BgColor.YELLOW,
    BgColor.CYAN,
]


# Convenience functions for common use cases
def assign_region_colors(
    grid: Grid, regions: dict[Any, list[tuple[int, ...]]], color_palette: list[BgColor] | None = None
) -> dict[Any, BgColor]:
    """
    Convenience function to color regions.

    Args:
        grid: The grid containing the regions
        regions: Dict mapping region IDs to lists of cell locations
        color_palette: Colors to use (defaults to a standard palette)

    Returns:
        Dictionary mapping region IDs to background colors
    """
    if color_palette is None:
        color_palette = DEFAULT_PALETTE

    coloring = RegionColoring(grid)
    return coloring.color_regions(regions, color_palette)


def assign_region_colors_from_predicates(
    grid: Grid,
    region_predicates: list[Predicate],
    id_field: str = "id",
    loc_field: str = "loc",
    color_palette: list[BgColor] | None = None,
) -> dict[Any, BgColor]:
    """
    Convenience function to color regions directly from predicate instances.

    Args:
        grid: The grid containing the regions
        region_predicates: List of predicate instances with region ID and location
        id_field: Name of the field containing region ID (default: "id")
        loc_field: Name of the field containing cell location (default: "loc")
        color_palette: Colors to use (defaults to a standard palette)

    Returns:
        Dictionary mapping region IDs to background colors
    """
    if color_palette is None:
        color_palette = DEFAULT_PALETTE

    coloring = RegionColoring(grid)
    return coloring.color_regions_from_predicate(region_predicates, id_field, loc_field, color_palette)
