from typing import Any

from aspuzzle.grids.region_coloring import assign_region_colors
from aspuzzle.grids.rendering import BgColor, Color
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import ANY, Predicate, create_variables


class Starbattle(Solver):
    solver_name = "Starbattle puzzle solver"
    default_config = {"star_count": 1}
    map_grid_to_integers = True
    _region_colors: dict[Any, BgColor]

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        star_count = puzzle.register_symbolic_constant("star_count", config["star_count"])

        # Define predicates
        Region = Predicate.define("region", ["loc", "id"], show=False)
        N, Dir = create_variables("N", "Dir")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define regions
        puzzle.blank_line(segment="Regions")
        puzzle.fact(
            *[Region(loc=grid.Cell(*loc), id=region_id) for loc, region_id in grid_data],
            segment="Regions",
        )

        # Define star placement
        symbols = SymbolSet(grid).add_symbol("star")

        # Rule 1: Place star_count stars on each line (row/column/etc) and region
        puzzle.section("Star placement rules")

        # 1a) Per line (row or column): exactly star_count stars in each line
        puzzle.count_constraint(
            count_over=cell,
            condition=[symbols["star"](cell), grid.Line(direction=Dir, index=N, loc=cell)],
            when=grid.Line(direction=Dir, index=N, loc=ANY),
            exactly=star_count,
        )

        # 1b) Per region: exactly star_count stars in each region
        puzzle.count_constraint(
            count_over=cell,
            condition=[symbols["star"](cell), Region(loc=cell, id=N)],
            when=Region(loc=ANY, id=N),
            exactly=star_count,
        )

        # Rule 2: Stars cannot share a vertex or edge
        puzzle.section("Star adjacency constraints")
        puzzle.forbid(symbols["star"](cell), symbols["star"](cell_adj), grid.vertex_sharing(suffix_2="adj"))

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Star Battle solver.

        Returns:
            Dictionary with rendering configuration for Star Battle
        """
        puzzle_symbols = {}
        for region_id, background_color in self._region_colors.items():
            puzzle_symbols[region_id] = {"background": background_color, "symbol": "."}

        return {
            "puzzle_symbols": puzzle_symbols,
            "predicates": {
                "star": {"symbol": "★", "color": Color.BRIGHT_YELLOW},
            },
            "join_char": "",
        }

    def _preprocess_config(self) -> None:
        """Precompute region colors for rendering."""
        regions: dict[Any, list[tuple[int, ...]]] = {}
        for loc, region_id in self.grid_data:
            regions.setdefault(region_id, []).append(loc)

        colors = [
            BgColor.BRIGHT_BLUE,
            BgColor.GREEN,
            BgColor.RED,
            BgColor.CYAN,
        ]

        self._region_colors = assign_region_colors(self.grid, regions, color_palette=colors)
