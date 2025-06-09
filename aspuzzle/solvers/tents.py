from typing import Any

from aspuzzle.grids.rendering import Color, RenderSymbol
from aspuzzle.solvers.base import Solver
from pyclingo import ANY, Choice, Predicate, create_variables


class Tents(Solver):
    solver_name = "Tents puzzle solver"
    supported_symbols = [".", "T"]

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data()

        # Define predicates
        Tree = Predicate.define("tree", ["loc"], show=False)
        Tent = Predicate.define("tent", ["loc"], show=True)
        Tie = Predicate.define("tie", ["tree_loc", "dir"], show=False)
        TieDestination = Predicate.define("tie_destination", ["tree_loc", "tent_loc"], show=False)
        ExpectedCounts = Predicate.define("expected_count", ["dir", "index", "count"], show=False)

        # Create variables
        C, N, D, A, B, Clue = create_variables("C", "N", "D", "A", "B", "Clue")
        cell = grid.cell()
        vec = grid.cell(suffix="vec")

        # Define trees from input
        puzzle.section("Trees", segment="Clues")
        puzzle.fact(*[Tree(loc=grid.Cell(*loc)) for loc, _ in grid_data], segment="Clues")

        # Define expected line counts
        puzzle.section("Tent counts", segment="Clues")
        for direction in grid.line_direction_names:
            clue_key = f"{grid.line_direction_descriptions[direction]}_clues"
            for i, count in enumerate(config[clue_key], 1):
                if count is not None:
                    puzzle.fact(ExpectedCounts(dir=direction, index=i, count=count), segment="Clues")

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
                grid.Direction(D, vector=vec),
            ],
            let=TieDestination(tree_loc=cell, tent_loc=grid.add_vector_to_cell(cell, vec)),
        )

        # Rule 2: Place tents and validate their location
        puzzle.section("Tent placement")
        puzzle.when(TieDestination(tree_loc=ANY, tent_loc=C), Tent(loc=C))
        # Tents can only be placed in a valid cell
        puzzle.forbid(Tent(loc=cell), ~cell)
        # Tents cannot be placed on a tree
        puzzle.forbid(Tent(C), Tree(C))

        # Rule 3: Tents can't be shared by trees
        puzzle.when(
            [
                TieDestination(tree_loc=A, tent_loc=C),
                TieDestination(tree_loc=B, tent_loc=C),
            ],
            let=(A == B),
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

    def validate_config(self) -> None:
        """Validate the puzzle configuration."""
        self.validate_line_clues()

    def get_render_config(self) -> dict[str, Any]:
        """
        Get the rendering configuration for the Tents solver.

        Returns:
            Dictionary with rendering configuration for Tents
        """
        return {
            "puzzle_symbols": {
                "T": RenderSymbol("T", Color.GREEN),
            },
            "predicates": {
                "tent": {"symbol": "A", "color": Color.YELLOW},
            },
        }
