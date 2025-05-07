#!/usr/bin/env python3
import argparse
import json
import pathlib

from aspuzzle.solvers.base import Solver


def solve(
    filename: str,
    preview_puzzle: bool = False,
    render: bool = True,
    solve_puzzle: bool = True,
    max_solutions: int = 0,
    timeout: int = 0,
    display_solutions: bool = True,
    display_stats: bool = True,
    visualize: bool = True,
    validate: bool = True,
    output_file: str | None = None,
    quiet: bool = False,
) -> None:
    """
    Loads the puzzle from the given filename and solves it based on options.

    Args:
        filename: Path to the puzzle JSON file
        preview_puzzle: Whether to preview the puzzle before solving
        render: Whether to render the ASP program
        solve_puzzle: Whether to solve the puzzle
        max_solutions: Maximum number of solutions to find (0 for all)
        timeout: Timeout in seconds (0 for no timeout)
        display_solutions: Whether to display found solutions
        display_stats: Whether to display solver statistics
        visualize: Whether to visualize the solution as ASCII
        validate: Whether to validate solutions against expected solutions
        output_file: Optional file to write the ASP program to
        quiet: Suppress all output except errors
    """
    # Find the file to open
    if not filename.endswith(".json"):
        filename += ".json"
    path = pathlib.Path(filename)

    if not path.exists():
        # Try looking in the puzzles directory
        path = path.parent / "puzzles" / filename

    if not path.exists():
        raise FileNotFoundError(f"Could not find puzzle file: {filename}")

    with open(path) as f:
        config = json.load(f)

    # Create the appropriate solver
    solver = Solver.from_config(config)

    # Construct the puzzle rules
    solver.construct_puzzle()

    # Preview the puzzle if requested
    if preview_puzzle and not quiet:
        print("\n=== Puzzle Preview ===")
        print(solver.render_puzzle())

    # Render the puzzle
    if render and not quiet:
        print("\n=== Clingo Script ===")
        asp_program = solver.puzzle.render()
        print(asp_program)

        if output_file:
            output_path = pathlib.Path(output_file)
            with open(output_path, "w") as f:
                f.write(asp_program)
            print(f"\nASP program written to {output_path}")

    # Solve the puzzle
    if solve_puzzle:
        solutions = solver.solve(models=max_solutions, timeout=timeout)

        # Display solutions
        if display_solutions and not quiet:
            solver.display_results(solutions, visualize=visualize)

        # Print statistics
        if display_stats and not quiet:
            solver.display_statistics()

        # Validate solutions
        if validate and not quiet and "solutions" in config:
            solver.validate_solutions(solutions)


def main() -> None:
    """Main entry point for the solver CLI."""
    parser = argparse.ArgumentParser(
        description="ASPuzzle solver CLI tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("filename", help="Path to puzzle JSON file (with or without .json extension)")

    # Render options
    render_group = parser.add_argument_group("Rendering options")
    render_group.add_argument("--no-preview", action="store_true", help="Suppress the puzzle preview before solving")
    render_exclusive = render_group.add_mutually_exclusive_group()
    render_exclusive.add_argument("--render", action="store_true", help="Render the ASP program (default)")
    render_exclusive.add_argument("--no-render", action="store_true", help="Don't render the ASP program")
    render_exclusive.add_argument(
        "--render-only", action="store_true", help="Only render the ASP program without solving"
    )
    render_group.add_argument("--output-file", "-o", help="Write the ASP program to this file")

    # Solve options
    solve_group = parser.add_argument_group("Solving options")
    solve_group.add_argument(
        "--max-solutions", "-m", type=int, default=0, help="Maximum number of solutions to find (0 for all)"
    )
    solve_group.add_argument("--timeout", "-t", type=int, default=0, help="Timeout in seconds (0 for no timeout)")

    # Display options
    display_group = parser.add_argument_group("Display options")
    display_group.add_argument("--no-solutions", action="store_true", help="Don't display solutions")
    display_group.add_argument("--stats", action="store_true", help="Display solver statistics")
    display_group.add_argument("--no-viz", action="store_true", help="Don't visualize the solution")
    display_group.add_argument(
        "--no-validation", action="store_true", help="Don't validate solutions against expected solutions"
    )
    display_group.add_argument("--quiet", "-q", action="store_true", help="Suppress all output except errors")

    # Parse arguments
    args = parser.parse_args()

    # Determine rendering option
    render = not args.no_render
    solve_puzzle = not args.render_only

    solve(
        filename=args.filename,
        preview_puzzle=not args.no_preview,
        render=render,
        solve_puzzle=solve_puzzle,
        max_solutions=args.max_solutions,
        timeout=args.timeout,
        display_solutions=not args.no_solutions and not args.quiet,
        display_stats=args.stats and not args.quiet,
        visualize=not args.no_viz and not args.quiet,
        validate=not args.no_validation and not args.quiet,
        output_file=args.output_file,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
