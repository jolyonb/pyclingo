from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet, set_count_constraint
from aspuzzle.utils import read_grid
from pyclingo import (
    ANY,
    Predicate,
    create_variables,
    Count,
    Equals,
)

default_config = {
    "star_count": 1,
}


class Starbattle(Solver):
    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        grid = self.grid
        puzzle = self.puzzle
        puzzle.name = "Starbattle puzzle solver"

        # Merge default config
        config = {**default_config, **self.config}
        star_count = puzzle.register_symbolic_constant("star_count", config["star_count"])

        # Define predicates
        Region = Predicate.define("region", ["loc", "id"], show=False)
        N, Dir = create_variables("N", "Dir")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define regions
        puzzle.blank_line(segment="Regions")
        regions = read_grid(config["regions"])
        puzzle.fact(
            *[Region(loc=grid.Cell(row=r, col=c), id=region_id) for r, c, region_id in regions],
            segment="Regions",
        )

        # Define star placement
        symbols = SymbolSet(grid).add_symbol("star")

        # Rule 1: Place star_count stars on each line (row/column/etc) and region
        puzzle.section("Star placement rules")

        # Per line (row or column): exactly star_count stars in each line
        set_count_constraint(
            grid=grid,
            predicate=symbols["star"](cell),
            exactly=star_count,
            count_conditions=grid.Line(direction=Dir, index=N, loc=cell),
            rule_terms=grid.Line(direction=Dir, index=N, loc=ANY),
        )

        # Per region: exactly star_count stars in each region
        set_count_constraint(
            grid=grid,
            predicate=symbols["star"](cell),
            exactly=star_count,
            count_conditions=Region(loc=cell, id=N),
            rule_terms=Region(loc=ANY, id=N),
        )

        # Rule 2: Stars cannot be touching (including diagonally)
        puzzle.section("Star adjacency constraints")
        puzzle.forbid(symbols["star"](cell), symbols["star"](cell_adj), grid.vertex_sharing(suffix_2="adj"))
