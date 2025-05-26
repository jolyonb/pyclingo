from typing import Any

from aspuzzle.grids.rendering import Color
from aspuzzle.solvers.base import Solver
from pyclingo import ANY, Choice, Not, Predicate, create_variables


class Numberlink(Solver):
    solver_name = "Numberlink puzzle solver"

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Create variables
        Cell, Cell1, Cell2, D, OppD, Sym, N = create_variables("Cell", "Cell1", "Cell2", "D", "OppD", "Sym", "N")

        # Clues
        Symbol = Predicate.define("symbol", ["loc", "sym"], show=False)
        puzzle.section("Define numbered endpoints", segment="Clues")
        puzzle.fact(
            *[Symbol(loc=grid.Cell(*loc), sym=sym) for loc, sym in grid_data],
            segment="Clues",
        )

        # Define which cells have symbols
        puzzle.section("Identify cells with symbols")
        HasSymbol = Predicate.define("has_symbol", ["loc"], show=False)
        puzzle.when(Symbol(loc=Cell, sym=ANY), HasSymbol(loc=Cell))

        # Rule 1: Define how many paths each cell should have
        puzzle.section("Path degree requirements")
        cell = grid.cell()
        PathDegree = Predicate.define("path_degree", ["loc", "degree"], show=False)
        puzzle.when(HasSymbol(loc=Cell), PathDegree(loc=Cell, degree=1))
        puzzle.when([cell, Not(HasSymbol(loc=cell))], PathDegree(loc=cell, degree=2))

        # Rule 2: Choose path directions for each cell
        puzzle.section("Path choice constraints")
        Path = Predicate.define("path", ["loc", "direction"], show=False)
        puzzle.when(
            PathDegree(loc=cell, degree=N),
            Choice(
                element=Path(loc=cell, direction=D),
                condition=grid.OrthogonalDir(cell1=cell, direction=D, cell2=ANY),
            ).exactly(N),
        )

        # Rule 3: If a cell has a path in a direction, the adjacent cell must have a path back
        puzzle.section("Bidirectional path constraint")
        puzzle.forbid(
            Path(loc=Cell1, direction=D),
            grid.OrthogonalDir(cell1=Cell1, cell2=Cell2, direction=D),
            grid.Opposite(D, OppD),
            Not(Path(loc=Cell2, direction=OppD)),
        )

        # Rule 4: Cells with symbols propagate their symbol
        puzzle.section("Symbol propagation")
        PropagatedSymbol = Predicate.define("propagated_symbol", ["loc", "sym"], show=False)
        puzzle.when(Symbol(loc=Cell, sym=Sym), PropagatedSymbol(loc=Cell, sym=Sym))

        # Rule 5: Symbols propagate through connected paths
        puzzle.when(
            [
                PropagatedSymbol(loc=Cell1, sym=Sym),
                Path(loc=Cell1, direction=D),
                grid.OrthogonalDir(cell1=Cell1, cell2=Cell2, direction=D),
            ],
            PropagatedSymbol(loc=Cell2, sym=Sym),
        )

        # Rule 6: Each cell must have exactly one propagated symbol
        puzzle.section("Unique symbol per cell")
        puzzle.count_constraint(count_over=Sym, condition=PropagatedSymbol(loc=cell, sym=Sym), when=cell, exactly=1)

        # Rule 7: Orthogonal cells with the same propagated symbol must be connected via path
        puzzle.section("Define connected relationship")
        Connected = Predicate.define("connected", ["loc1", "loc2"], show=False)
        puzzle.when(
            [
                Path(loc=Cell1, direction=D),
                grid.OrthogonalDir(cell1=Cell1, cell2=Cell2, direction=D),
            ],
            Connected(loc1=Cell1, loc2=Cell2),
        )

        puzzle.section("No self-touch constraint")
        puzzle.forbid(
            grid.Orthogonal(cell1=Cell1, cell2=Cell2),
            PropagatedSymbol(loc=Cell1, sym=Sym),
            PropagatedSymbol(loc=Cell2, sym=Sym),
            Not(Connected(loc1=Cell1, loc2=Cell2)),
        )

        # Rule 8: Solution extraction - compute the two directions for each non-symbol cell
        puzzle.section("Solution extraction")
        CellDirections = Predicate.define("cell_directions", ["loc", "dir1", "dir2"], show=True)
        D1, D2 = create_variables("D1", "D2")

        puzzle.when(
            [
                cell,
                Not(HasSymbol(loc=cell)),
                Path(loc=cell, direction=D1),
                Path(loc=cell, direction=D2),
                D1 < D2,  # Ensure canonical ordering to avoid duplicates
            ],
            CellDirections(loc=cell, dir1=D1, dir2=D2),
        )

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Numberlink solver.

        Returns:
            Dictionary with rendering configuration for Numberlink
        """
        # Colors for numbers 1-9, cycling for higher numbers
        colors = [
            Color.BLUE,  # 1
            Color.GREEN,  # 2
            Color.RED,  # 3
            Color.MAGENTA,  # 4
            Color.CYAN,  # 5
            Color.YELLOW,  # 6
            Color.BRIGHT_BLUE,  # 7
            Color.BRIGHT_GREEN,  # 8
            Color.BRIGHT_RED,  # 9
        ]

        puzzle_symbols = {
            i: {
                "symbol": str(i) if i <= 9 else "#",
                "color": colors[(i - 1) % len(colors)],
            }
            for i in range(1, 100)
        }

        return {
            "puzzle_symbols": puzzle_symbols,
            "predicates": {
                "cell_directions": {"loop_directions": True, "color": Color.CYAN},
            },
            "join_char": "",
        }
