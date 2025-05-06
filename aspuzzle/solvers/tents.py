from aspuzzle.solvers.base import Solver
from pyclingo import ANY, Choice, Equals, Not, Predicate, create_variables
from pyclingo.value import SymbolicConstant


class Tents(Solver):
    solver_name = "Tents puzzle solver"
    supported_symbols = [".", "T"]

    def construct_puzzle(self) -> None:
        """Construct the rules of the puzzle."""
        puzzle, grid, config, grid_data = self.unpack_data

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
        puzzle.fact(*[Tree(loc=grid.Cell(row=r, col=c)) for r, c, _ in grid_data], segment="Clues")

        # Define expected line counts
        puzzle.section("Tent counts", segment="Clues")

        # Process each direction defined in the grid's line_direction_names
        for direction in grid.line_direction_names:
            clue_key = f"{grid.line_direction_descriptions[direction]}_clues"
            for i, count in enumerate(config[clue_key], 1):
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

    def validate_config(self) -> None:
        """Validate the puzzle configuration."""
        grid = self.grid

        # Check if line clues exist for each direction
        for direction in grid.line_direction_names:
            clue_key = f"{grid.line_direction_descriptions[direction]}_clues"
            if clue_key not in self.config:
                raise ValueError(f"Missing {clue_key} in puzzle configuration")

        # Get the number of lines in each direction
        line_sums = []
        for direction in grid.line_direction_names:
            clue_key = f"{grid.line_direction_descriptions[direction]}_clues"
            expected_count = grid.get_line_count(direction)
            actual_count = len(self.config[clue_key])

            if isinstance(expected_count, SymbolicConstant):
                # Can't verify if we have a symbolic constant
                pass
            elif actual_count == expected_count:
                line_sums.append((direction, sum(self.config[clue_key])))
            else:
                raise ValueError(f"Expected {expected_count} {clue_key}, got {actual_count}")

        # Ensure all line sums are equal to each other and to the tree count
        if line_sums:
            expected_sum = line_sums[0][1]
            for direction, actual_sum in line_sums[1:]:
                if actual_sum != expected_sum:
                    desc1 = grid.line_direction_descriptions[line_sums[0][0]]
                    desc2 = grid.line_direction_descriptions[direction]
                    raise ValueError(
                        f"Sum of {desc1} clues ({expected_sum}) doesn't match sum of {desc2} clues ({actual_sum})"
                    )

            # Count the number of trees in the grid
            tree_count = len(self.grid_data)

            # Check that sum matches tree count
            if expected_sum != tree_count:
                raise ValueError(f"Sum of clues ({expected_sum}) doesn't match number of trees ({tree_count})")
