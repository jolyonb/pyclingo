from aspuzzle.grids.rectangulargrid import RectangularGrid
from aspuzzle.solvers.base import Solver
from aspuzzle.symbolset import SymbolSet
from pyclingo import ANY, Predicate, create_variables


class Minesweeper(Solver):
    solver_name = "Minesweeper puzzle solver"
    default_config = {
        "num_mines": None,
    }
    supported_symbols = list(range(10)) + ["."]

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config = self.pgc
        grid_data = self.parse_grid(config["grid"])
        assert isinstance(grid, RectangularGrid)

        # Define predicates
        Number = Predicate.define("number", ["loc", "num"], show=False)
        N = create_variables("N")
        cell = grid.cell()
        cell_adj = grid.cell(suffix="adj")

        # Define clues
        puzzle.blank_line(segment="Clues")
        puzzle.fact(
            *[Number(loc=grid.Cell(row=r, col=c), num=num) for r, c, num in grid_data],
            segment="Clues",
        )

        # Define mine placement
        symbols = SymbolSet(grid).add_symbol("mine").excluded_symbol(Number(loc=cell, num=ANY))

        # Rule 1: Each number indicates exactly how many mines are adjacent
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

        # (Optional) Rule 2: Global mine count constraint
        if config["num_mines"]:
            puzzle.section("Mine count constraint")
            puzzle.count_constraint(count_over=cell, condition=symbols["mine"](loc=cell), exactly=config["num_mines"])
