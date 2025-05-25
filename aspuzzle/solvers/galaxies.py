from typing import Any

from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.grids.region_coloring import assign_region_colors_from_predicates
from aspuzzle.grids.rendering import BgColor, Color, RenderItem
from aspuzzle.regionconstructor import RegionConstructor
from aspuzzle.solvers.base import Solver
from pyclingo import ANY, Not, Predicate, create_variables


class Galaxies(Solver):
    """
    This is a galaxies solver on a rectangular grid.

    Because the point symmetry rule is intrinsically tied to the geometry of the grid, we will implement separate
    solvers for different grid geometries.
    """

    solver_name = "Spiral Galaxies solver"
    supported_grid_types = (RectangularGrid,)
    supported_symbols = [".", "o", "<", ">", "^", "v", 1, 2, 3, 4]
    _region_colors: dict[Any, BgColor] | None = None

    def validate_config(self) -> None:
        """Validate the puzzle configuration."""
        self.process_data()

    def process_data(self) -> list[tuple[tuple[int, int], tuple[int, int], int]]:
        """
        Process the grid data to identify galaxy centers and their positions.

        Returns:
            List of (center_position1, center_position2, region_id) tuples.
            For centers in cells, position1 = position2.
            For centers at edges or corners, position1 and position2 are the adjacent cells that average to the center.
        """
        # Parse the grid to find all markers
        cell_markers = {}
        for r, row in enumerate(self.config["grid"], 1):
            for c, symbol in enumerate(row, 1):
                if symbol != ".":
                    cell_markers[(r, c)] = symbol

        # Process the markers to identify centers
        centers: list[tuple[tuple[int, int], tuple[int, int], int]] = []
        processed = set()
        region_id = 1

        for (r, c), symbol in cell_markers.items():
            if (r, c) in processed:
                continue

            if symbol == "1":
                # For a "1" cell at (r,c), we need to check if "2", "3", and "4" are present
                # in their expected positions
                expected = {
                    "2": (r, c + 1),  # Top-right
                    "3": (r + 1, c),  # Bottom-left
                    "4": (r + 1, c + 1),  # Bottom-right
                }
                valid = not any(
                    pos not in cell_markers or cell_markers[pos] != expected_symbol
                    for expected_symbol, pos in expected.items()
                )
                if not valid:
                    raise ValueError(f"Incomplete vertex definition at cell ({r}, {c})")
                centers.append(((r, c), (r + 1, c + 1), region_id))
                processed.add((r, c))
                processed.add((r, c + 1))
                processed.add((r + 1, c))
                processed.add((r + 1, c + 1))
                region_id += 1

            elif symbol == "<":
                # For a "<" cell at (r,c), we need to check if ">" is present next to it
                if (r, c + 1) not in cell_markers or cell_markers[(r, c + 1)] != ">":
                    raise ValueError(f"Incomplete vertex definition at cell ({r}, {c})")
                centers.append(((r, c), (r, c + 1), region_id))
                processed.add((r, c))
                processed.add((r, c + 1))
                region_id += 1

            elif symbol == "^":
                # For a "^" cell at (r,c), we need to check if "v" is present below it
                if (r + 1, c) not in cell_markers or cell_markers[(r + 1, c)] != "v":
                    raise ValueError(f"Incomplete vertex definition at cell ({r}, {c})")
                centers.append(((r, c), (r + 1, c), region_id))
                processed.add((r, c))
                processed.add((r + 1, c))
                region_id += 1

            elif symbol == "o":
                centers.append(((r, c), (r, c), region_id))
                processed.add((r, c))
                region_id += 1

        # Check for orphaned characters
        if orphaned := set(cell_markers.keys()) - processed:
            orphaned_symbols = {pos: cell_markers[pos] for pos in orphaned}
            raise ValueError(f"Orphaned galaxy markers detected: {orphaned_symbols}")

        return centers

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()
        assert isinstance(grid, RectangularGrid)

        # Define predicates
        Center = Predicate.define("center", ["loc", "loc2", "id"], show=False)

        # Define clues - the clues contain cells on either side of the center
        puzzle.fact(
            *[
                Center(loc=grid.Cell(*loc1), loc2=grid.Cell(*loc2), id=region_id)
                for loc1, loc2, region_id in self.process_data()
            ],
            segment="Clues",
        )

        # Divide the grid into regions using the first cell in each clue as an anchor
        region_constructor = RegionConstructor(
            puzzle=puzzle,
            grid=grid,
            anchor_predicate=Center,
            anchor_fields={"loc2": ANY, "id": ANY},
            allow_regionless=False,
        )

        # Impose the symmetry constraint
        puzzle.section("Symmetry rule")
        R, C, R1, C1, R2, C2, Id = create_variables("R", "C", "R1", "C1", "R2", "C2", "Id")
        puzzle.forbid(
            Center(loc=grid.Cell(R1, C1), loc2=grid.Cell(R2, C2), id=Id),
            region_constructor.Region(loc=grid.Cell(R, C), anchor=grid.Cell(R1, C1)),
            Not(region_constructor.Region(loc=grid.Cell(R1 + R2 - R, C1 + C2 - C), anchor=grid.Cell(R1, C1))),
        )

        # Define a predicate to extract the regions from the puzzle for solution display purposes
        puzzle.section("Solution extraction")
        Galaxy = Predicate.define("galaxy", ["loc", "id"], show=True)
        Loc, A, Id = create_variables("Loc", "A", "Id")
        puzzle.when(
            [
                region_constructor.Region(loc=Loc, anchor=A),
                Center(loc=A, loc2=ANY, id=Id),
            ],
            let=Galaxy(loc=Loc, id=Id),
        )

    def get_render_config(self) -> dict[str, Any]:
        """Get the rendering configuration for the Galaxies solver."""

        def region_renderer(pred: Predicate) -> list[RenderItem]:
            """Custom renderer that uses precomputed colors."""
            region_id = pred["id"].value

            # Use precomputed color if available, otherwise fall back
            if self._region_colors and region_id in self._region_colors:
                background = self._region_colors[region_id]
            else:
                # Fallback - shouldn't happen if preprocess_for_rendering was called
                background = BgColor.BRIGHT_BLACK

            return [
                RenderItem(
                    loc=pred["loc"],
                    symbol=None,
                    background=background,
                )
            ]

        return {
            "puzzle_symbols": {
                ".": {"symbol": ".", "color": Color.WHITE},  # Dot for empty cells
                "o": {"symbol": "o", "color": Color.BRIGHT_RED},
                "^": {"symbol": "^", "color": Color.BRIGHT_RED},
                "v": {"symbol": "v", "color": Color.BRIGHT_RED},
                "<": {"symbol": "<", "color": Color.BRIGHT_RED},
                ">": {"symbol": ">", "color": Color.BRIGHT_RED},
                1: {"symbol": "/", "color": Color.BRIGHT_RED},
                2: {"symbol": "\\", "color": Color.BRIGHT_RED},
                3: {"symbol": "\\", "color": Color.BRIGHT_RED},
                4: {"symbol": "/", "color": Color.BRIGHT_RED},
            },
            "predicates": {
                "galaxy": {"custom_renderer": region_renderer},
            },
            "join_char": "",
        }

    def _preprocess_for_rendering(self, solution: dict[str, list[Predicate]] | None = None) -> None:
        """Precompute region colors for efficient rendering."""
        if not solution or "galaxy" not in solution:
            return

        self._region_colors = assign_region_colors_from_predicates(
            self.grid, solution["galaxy"], id_field="id", loc_field="loc"
        )
