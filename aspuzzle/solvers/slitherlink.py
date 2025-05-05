from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from aspuzzle.utils import read_grid
from pyclingo import Not, Predicate, create_variables


class Slitherlink(Solver):
    solver_name = "Slitherlink puzzle solver"

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config = self.pgc

        # Define predicates
        Clue = Predicate.define("clue", ["loc", "num"], show=False)
        Sheep = Predicate.define("sheep", ["loc"], show=False)
        Wolf = Predicate.define("wolf", ["loc"], show=False)

        # Create variables
        N, C, C_adj = create_variables("N", "C", "C_adj")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Parse clues, sheep, and wolves from the grid
        puzzle.section("Grid data", segment="Clues")
        grid_data = read_grid(config["clue_grid"])

        # Define clues
        puzzle.fact(
            *[Clue(loc=grid.Cell(row=r, col=c), num=v) for r, c, v in grid_data if isinstance(v, int) and 0 <= v <= 3],
            segment="Clues",
        )

        # Define sheep
        sheep_facts = [Sheep(loc=grid.Cell(row=r, col=c)) for r, c, v in grid_data if v == "S"]
        if sheep_facts:
            puzzle.fact(*sheep_facts, segment="Clues")

        # Define wolves
        wolf_facts = [Wolf(loc=grid.Cell(row=r, col=c)) for r, c, v in grid_data if v == "W"]
        if wolf_facts:
            puzzle.fact(*wolf_facts, segment="Clues")

        # Define inside/outside regions
        symbols = SymbolSet(grid, fill_all_squares=True).add_symbol("inside").add_symbol("outside")

        # Rule 1: All outside border cells are outside
        puzzle.section("Outside border cells must be outside")
        puzzle.when(grid.OutsideGrid(C), symbols["outside"](C))

        # Rule 2: Sheep must be inside, wolves must be outside
        if sheep_facts:
            puzzle.section("Sheep constraints")
            puzzle.when(Sheep(C), symbols["inside"](C))

        if wolf_facts:
            puzzle.section("Wolf constraints")
            puzzle.when(Wolf(C), symbols["outside"](C))

        # Rule 3: Both inside and outside regions must be contiguous
        symbols.make_contiguous("inside")
        symbols.make_contiguous("outside", anchor_cell=grid.OutsideGrid(C))

        # Rule 4: Slitherlink clue constraints
        puzzle.section("Slitherlink clue constraints")

        puzzle.comment("Efficient handling for 0 clues")
        for t in ("inside", "outside"):
            puzzle.forbid(
                Clue(loc=C, num=0),
                symbols[t](loc=C),
                Not(symbols[t](loc=C_adj)),
                grid.Orthogonal(C, C_adj),
            )

        puzzle.comment("General handling for 1/2/3 clues")
        # Count outside neighbors when the clue cell is inside
        puzzle.count_constraint(
            count_over=cell_adj,
            condition=[
                grid.orthogonal(),
                symbols["outside"](loc=cell_adj),
            ],
            when=[Clue(loc=cell, num=N), N > 0, symbols["inside"](loc=cell)],
            exactly=N,
        )

        # Count inside neighbors when the clue cell is outside
        puzzle.count_constraint(
            count_over=cell_adj,
            condition=[
                grid.orthogonal(),
                symbols["inside"](loc=cell_adj),
            ],
            when=[Clue(loc=cell, num=N), N > 0, symbols["outside"](loc=cell)],
            exactly=N,
        )
