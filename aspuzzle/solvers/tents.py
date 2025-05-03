from aspuzzle.solvers.base import Solver
from aspuzzle.utils import read_grid
from pyclingo import ANY, Choice, Equals, Not, Predicate, create_variables


class Tents(Solver):
    solver_name = "Tents puzzle solver"

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config = self.pgc

        # Define predicates
        Tree = Predicate.define("tree", ["loc"], show=False)
        Tent = Predicate.define("tent", ["loc"], show=True)
        Tie = Predicate.define("tie", ["tree_loc", "dir"], show=False)
        TieDestination = Predicate.define("tie_destination", ["tree_loc", "tent_loc"], show=False)
        ExpectedCounts = Predicate.define("expected_count", ["dir", "index", "count"], show=False)

        # Create variables
        R, C, N, D, DR, DC, A, B, Clue = create_variables("R", "C", "N", "D", "DR", "DC", "A", "B", "Clue")
        cell = grid.cell()

        # Define trees from input
        puzzle.section("Trees", segment="Clues")
        tree_locations = read_grid(config["tree_grid"])
        puzzle.fact(
            *[Tree(loc=grid.Cell(row=r, col=c)) for r, c, _ in tree_locations], segment="Clues"
        )

        # Define expected row and column counts
        puzzle.section("Tent counts", segment="Clues")
        # Row counts (direction 'e' for rows)
        for i, count in enumerate(config["row_clues"], 1):
            puzzle.fact(ExpectedCounts(dir="e", index=i, count=count), segment="Clues")
        # Column counts (direction 's' for columns)
        for i, count in enumerate(config["col_clues"], 1):
            puzzle.fact(ExpectedCounts(dir="s", index=i, count=count), segment="Clues")

        # Rule 1: Each tree has exactly one tie in an orthogonal direction
        puzzle.section("Tree ties")
        # Decide on the direction
        puzzle.when(
            Tree(loc=C),
            let=Choice(
                element=Tie(tree_loc=C, dir=D),
                condition=grid.OrthogonalDirections(D),
            ).exactly(1),
        )
        # Determine where it ties to
        puzzle.when(
            [
                Tie(tree_loc=cell, dir=D),
                grid.Direction(D, vector=grid.Cell(row=DR, col=DC)),
            ],
            let=TieDestination(tree_loc=cell, tent_loc=grid.Cell(row=R + DR, col=C + DC)),
        )

        # Rule 2: Place tents and validate their location
        puzzle.section("Tent placement")
        puzzle.when(TieDestination(tree_loc=ANY, tent_loc=C), Tent(loc=C))
        # Tents can only be placed in a valid cell
        puzzle.forbid(Tent(loc=cell), Not(cell))
        # Tents cannot be placed on a tree
        puzzle.forbid(Tent(C), Tree(C))

        # Rule 3: Tents can't be shared by trees
        puzzle.when(
            [
                TieDestination(tree_loc=A, tent_loc=C),
                TieDestination(tree_loc=B, tent_loc=C),
            ],
            let=Equals(A, B),
        )

        # Rule 4: Constraint on number of tents per line
        puzzle.section("Line tent count constraints")
        puzzle.count_constraint(
            count_over=cell,
            condition=[
                Tent(loc=cell),
                grid.Line(direction=D, index=N, loc=cell),
            ],
            when=ExpectedCounts(dir=D, index=N, count=Clue),
            exactly=Clue,
        )

        # Rule 5: Tents cannot share a vertex
        puzzle.section("Tent adjacency constraints")
        puzzle.forbid(Tent(A), Tent(B), grid.VertexSharing(A, B))
