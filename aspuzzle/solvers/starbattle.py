from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from aspuzzle.utils import read_grid
from pyclingo import (
    ANY,
    Choice,
    Predicate,
    RangePool,
    create_variables,
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
        star_count = config["star_count"]

        # Define predicates
        Region = Predicate.define("region", ["loc", "id"], show=False)
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # TODO: We have a fixation on rows and columns here; need to move to generic grid constructions
        N, R, C = create_variables("N", "R", "C")
        Rows = Predicate.define("rows", ["row"], show=False)
        puzzle.when(R.in_(RangePool(1, grid.rows)), Rows(row=R))
        Columns = Predicate.define("columns", ["col"], show=False)
        puzzle.when(C.in_(RangePool(1, grid.cols)), Columns(col=C))

        # Define regions
        puzzle.blank_line(segment="Regions")
        regions = read_grid(config["regions"])
        puzzle.fact(
            *[Region(loc=grid.Cell(row=r, col=c), id=region_id) for r, c, region_id in regions],
            segment="Regions",
        )

        # Define star placement
        symbols = SymbolSet(grid).add_symbol("star")
        Star = symbols["star"]

        # Rule 1: Place star_count stars on each row, column and region
        puzzle.section("Star placement rules")
        # TODO: Rewrite these in terms of counts? Need to be grid-agnostic regardless
        # Per row: exactly starcount stars in each row
        puzzle.when(Rows(R), Choice(Star(cell), condition=Columns(C)).exactly(star_count))
        # Per column: exactly starcount stars in each column
        puzzle.when(Columns(C), Choice(Star(cell), condition=Rows(R)).exactly(star_count))
        # Per region: exactly starcount stars in each region
        puzzle.when(Region(loc=ANY, id=N), Choice(Star(cell), condition=Region(cell, N)).exactly(star_count))

        # Rule 2: Stars cannot be touching (including diagonally)
        puzzle.section("Star adjacency constraints")
        puzzle.forbid(Star(cell), Star(cell_adj), grid.vertex_sharing(suffix_2="adj"))
