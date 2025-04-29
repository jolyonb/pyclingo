from aspuzzle.puzzle import Module, Puzzle, cached_predicate
from pyclingo import Abs, Predicate, RangePool, create_variables
from pyclingo.value import SymbolicConstant


class Grid(Module):
    """Module for grid-based puzzles with rows and columns."""

    def __init__(
        self,
        puzzle: Puzzle,
        rows: int | SymbolicConstant,
        cols: int | SymbolicConstant,
        name: str = "grid",
    ):
        """Initialize a grid module with specified dimensions."""
        super().__init__(puzzle, name)

        self.rows = rows
        self.cols = cols

    @cached_predicate
    def Cell(self) -> type[Predicate]:
        """Get the Cell predicate for this grid."""
        Cell = Predicate.define("cell", ["row", "col"], namespace=self.name, show=False)

        R, C = create_variables("R", "C")

        # Define grid cells
        self.section("Grid definition")
        self.when(
            [R.in_(RangePool(0, self.rows - 1)), C.in_(RangePool(0, self.cols - 1))],
            Cell(R, C),
        )

        return Cell

    def cell(self, suffix: str = "") -> Predicate:
        """Get a cell predicate for this grid with variable values."""
        if suffix:
            suffix = f"_{suffix}"
        R, C = create_variables(f"R{suffix}", f"C{suffix}")
        return self.Cell(row=R, col=C)

    @property
    def Adjacent(self) -> type[Predicate]:
        """Get the general adjacency predicate class (orthogonal or diagonal)."""
        Adjacent = Predicate.define(
            "adjacent", ["cell1", "cell2"], namespace=self.name, show=False
        )

        cell = self.cell()
        cell_adj = self.cell(suffix="adj")
        R, C, Radj, Cadj = create_variables("R", "C", "R_adj", "C_adj")

        self.section("Adjacency definition")
        self.when(
            [
                cell,
                cell_adj,
                Abs(R - Radj) <= 1,
                Abs(C - Cadj) <= 1,
                Abs(R - Radj) + Abs(C - Cadj) > 0,  # Not the same cell
            ],
            Adjacent(cell1=cell, cell2=cell_adj),
        )

        return Adjacent

    def adjacent(self, suffix_1: str = "", suffix_2: str = "adj") -> Predicate:
        """Get the general adjacency predicate class (orthogonal or diagonal)."""
        return self.Adjacent(self.cell(suffix_1), self.cell(suffix_2))
