from aspuzzle.grids.rectangulargrid import RectangularGrid, read_grid
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import ANY, Predicate, create_variables


class Starbattle_Shapeless(Solver):
    solver_name = "Shapeless Starbattle puzzle solver"
    default_config = {
        "star_count": 1,
    }
    supported_symbols = [".", "#"]

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config = self.pgc
        assert isinstance(grid, RectangularGrid)

        star_count = puzzle.register_symbolic_constant("star_count", config["star_count"])

        # Define predicates
        Excluded = Predicate.define("excluded", ["loc"], show=False)
        N, Dir = create_variables("N", "Dir")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define excluded area
        puzzle.blank_line(segment="Excluded cells")
        _, _, grid_data = read_grid(config["grid"])
        puzzle.fact(
            *[Excluded(loc=grid.Cell(row=r, col=c)) for r, c, _ in grid_data],
            segment="Excluded cells",
        )

        # Define star placement
        symbols = SymbolSet(grid).add_symbol("star").excluded_symbol(Excluded(loc=cell))

        # Rule 1: Place star_count stars on each line (row/column/etc)
        puzzle.section("Star placement rules")
        puzzle.count_constraint(
            count_over=cell,
            condition=[symbols["star"](cell), grid.Line(direction=Dir, index=N, loc=cell)],
            when=grid.Line(direction=Dir, index=N, loc=ANY),
            exactly=star_count,
        )

        # Rule 2: Stars cannot share a vertex or edge
        puzzle.section("Star adjacency constraints")
        puzzle.forbid(symbols["star"](cell), symbols["star"](cell_adj), grid.vertex_sharing(suffix_2="adj"))
