from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from aspuzzle.utils import read_grid
from pyclingo import ANY, Predicate, create_variables, Variable

default_config = {
    "num_mines": None,
}


class Minesweeper(Solver):

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        grid = self.grid
        puzzle = self.puzzle
        puzzle.name = "Minesweeper puzzle solver"

        # Merge default config
        config = {**default_config, **self.config}
        # Read in clues
        clues = read_grid(config["clue_grid"])

        # Define predicates
        Number = Predicate.define("number", ["loc", "num"], show=False)
        # Create variables
        N = Variable("N")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define mine placement
        symbols = SymbolSet(grid).add_symbol("mine").excluded_symbol(Number(loc=cell, num=ANY))

        # Number constraints: each number indicates exactly how many mines are adjacent
        puzzle.section("Numbers indicate the number of adjacent mines")
        puzzle.count_constraint(
            count_over=cell_adj,
            condition=[
                grid.VertexSharing(cell1=cell, cell2=cell_adj),
                symbols["mine"](loc=cell_adj),
            ],
            when=Number(loc=cell, num=N),
            exactly=N,
        )

        # Impose global mine count constraint
        if config["num_mines"]:
            puzzle.section("Mine count constraint")
            puzzle.count_constraint(
                count_over=grid.cell(),
                condition=symbols["mine"](loc=grid.cell()),
                exactly=config["num_mines"]
            )

        # Add clues
        puzzle.blank_line(segment="Clues")
        puzzle.fact(
            *[Number(loc=grid.Cell(row=r, col=c), num=num) for r, c, num in clues],
            segment="Clues",
        )
