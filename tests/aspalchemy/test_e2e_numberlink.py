"""
A full-size "real puzzle solves end to end" test.

This constructs a Numberlink solver in aspalchemy, solves it, and checks the single
answer set against the known-correct 63-atom solution. It is a standalone stress
test of the whole pipeline (compound terms nested as predicate arguments, a
variable-cardinality choice, recursive propagation, a count-aggregate
integrity constraint, typed reconstruction).
"""

import re

from aspalchemy import (
    ANY,
    ASPProgram,
    Choice,
    Count,
    ExplicitPool,
    Predicate,
    RangePool,
    Variable,
)

# 9x9 clue grid: digits are numbered endpoints, '.' is an empty cell.
GRID = [
    ".........",
    "....7.94.",
    "6.3......",
    "...8...5.",
    ".3.67....",
    "..8......",
    "2........",
    "....1....",
    "12....459",
]

# The eight compass directions with their (row, col) offset vectors.
DIRECTION_VECTORS = [
    ("n", (-1, 0)),
    ("ne", (-1, 1)),
    ("e", (0, 1)),
    ("se", (1, 1)),
    ("s", (1, 0)),
    ("sw", (1, -1)),
    ("w", (0, -1)),
    ("nw", (-1, -1)),
]

OPPOSITES = [
    ("n", "s"),
    ("ne", "sw"),
    ("e", "w"),
    ("se", "nw"),
    ("s", "n"),
    ("sw", "ne"),
    ("w", "e"),
    ("nw", "se"),
]

# The one known-correct answer set (63 atoms).
EXPECTED_CELL_DIRECTIONS = [
    'cell_directions(loc=cell(row=1, col=1), dir1="e", dir2="s")',
    'cell_directions(loc=cell(row=1, col=2), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=1, col=3), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=1, col=4), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=1, col=5), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=1, col=6), dir1="s", dir2="w")',
    'cell_directions(loc=cell(row=1, col=7), dir1="e", dir2="s")',
    'cell_directions(loc=cell(row=1, col=8), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=1, col=9), dir1="s", dir2="w")',
    'cell_directions(loc=cell(row=2, col=1), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=2, col=2), dir1="e", dir2="s")',
    'cell_directions(loc=cell(row=2, col=3), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=2, col=4), dir1="s", dir2="w")',
    'cell_directions(loc=cell(row=2, col=6), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=2, col=9), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=3, col=2), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=3, col=4), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=3, col=5), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=3, col=6), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=3, col=7), dir1="e", dir2="s")',
    'cell_directions(loc=cell(row=3, col=8), dir1="n", dir2="w")',
    'cell_directions(loc=cell(row=3, col=9), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=4, col=1), dir1="e", dir2="s")',
    'cell_directions(loc=cell(row=4, col=2), dir1="n", dir2="w")',
    'cell_directions(loc=cell(row=4, col=3), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=4, col=5), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=4, col=6), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=4, col=7), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=4, col=9), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=5, col=1), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=5, col=3), dir1="n", dir2="w")',
    'cell_directions(loc=cell(row=5, col=6), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=5, col=7), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=5, col=8), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=5, col=9), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=6, col=1), dir1="e", dir2="n")',
    'cell_directions(loc=cell(row=6, col=2), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=6, col=4), dir1="e", dir2="n")',
    'cell_directions(loc=cell(row=6, col=5), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=6, col=6), dir1="n", dir2="w")',
    'cell_directions(loc=cell(row=6, col=7), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=6, col=8), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=6, col=9), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=7, col=2), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=7, col=3), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=7, col=4), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=7, col=5), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=7, col=6), dir1="s", dir2="w")',
    'cell_directions(loc=cell(row=7, col=7), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=7, col=8), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=7, col=9), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=8, col=1), dir1="e", dir2="s")',
    'cell_directions(loc=cell(row=8, col=2), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=8, col=3), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=8, col=4), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=8, col=6), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=8, col=7), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=8, col=8), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=8, col=9), dir1="n", dir2="s")',
    'cell_directions(loc=cell(row=9, col=3), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=9, col=4), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=9, col=5), dir1="e", dir2="w")',
    'cell_directions(loc=cell(row=9, col=6), dir1="n", dir2="w")',
]

_EXPECTED_RE = re.compile(r'cell_directions\(loc=cell\(row=(\d+), col=(\d+)\), dir1="([a-z]+)", dir2="([a-z]+)"\)')


def _parse_endpoints(grid: list[str]) -> list[tuple[int, int, int]]:
    """Read numbered endpoints out of the clue grid as (row, col, value)."""
    endpoints: list[tuple[int, int, int]] = []
    for r, line in enumerate(grid, start=1):
        for c, ch in enumerate(line, start=1):
            if ch.isdigit():
                endpoints.append((r, c, int(ch)))
    return endpoints


def _parse_expected(strings: list[str]) -> set[tuple[int, int, str, str]]:
    """Turn the reference cell_directions atom strings into comparable tuples."""
    parsed: set[tuple[int, int, str, str]] = set()
    for atom in strings:
        match = _EXPECTED_RE.fullmatch(atom)
        assert match is not None, f"unparseable reference atom: {atom}"
        parsed.add((int(match.group(1)), int(match.group(2)), match.group(3), match.group(4)))
    return parsed


def _build_program() -> tuple[ASPProgram, type[Predicate]]:
    """Reproduce the generated numberlink.pl program in aspalchemy."""
    program = ASPProgram()

    # --- Predicates ---
    Cell = Predicate.define("cell", ["row", "col"], show=False)
    Direction = Predicate.define("direction", ["name", "vector"], show=False)
    OrthogonalDirections = Predicate.define("orthogonal_directions", ["name"], show=False)
    OrthogonalDir = Predicate.define("orthogonal_dir", ["cell1", "direction", "cell2"], show=False)
    Opposite = Predicate.define("opposite", ["dir1", "dir2"], show=False)
    Symbol = Predicate.define("symbol", ["loc", "sym"], show=False)
    HasSymbol = Predicate.define("has_symbol", ["loc"], show=False)
    PathDegree = Predicate.define("path_degree", ["loc", "degree"], show=False)
    Path = Predicate.define("path", ["loc", "direction"], show=False)
    PropagatedSymbol = Predicate.define("propagated_symbol", ["loc", "sym"], show=False)
    Connected = Predicate.define("connected", ["loc1", "loc2"], show=False)
    CellDirections = Predicate.define("cell_directions", ["loc", "dir1", "dir2"], show=True)

    # --- Variables ---
    R, C = Variable("R"), Variable("C")
    R_vec, C_vec = Variable("R_vec"), Variable("C_vec")
    D, OppD, Sym, N = Variable("D"), Variable("OppD"), Variable("Sym"), Variable("N")
    D1, D2 = Variable("D1"), Variable("D2")
    Cell_, Cell1, Cell2 = Variable("Cell"), Variable("Cell1"), Variable("Cell2")
    cell = Cell(row=R, col=C)

    # --- Grid scaffolding ---
    grid_seg = program.add_segment("grid")
    grid_seg.section("Define cells in the grid")
    grid_seg.when(R.in_(RangePool(1, 9)), C.in_(RangePool(1, 9))).derive(Cell(row=R, col=C))

    grid_seg.section("Define directions in the grid")
    grid_seg.fact(*[Direction(name=name, vector=Cell(row=dr, col=dc)) for name, (dr, dc) in DIRECTION_VECTORS])

    grid_seg.section("Orthogonal directions")
    grid_seg.fact(OrthogonalDirections(name=ExplicitPool(["n", "e", "s", "w"])))

    grid_seg.section("Orthogonal adjacency with direction definition")
    cell_plus_vector = Cell(row=R + R_vec, col=C + C_vec)
    grid_seg.when(
        cell,
        OrthogonalDirections(name=D),
        Direction(name=D, vector=Cell(row=R_vec, col=C_vec)),
        cell_plus_vector,
    ).derive(OrthogonalDir(cell1=cell, direction=D, cell2=cell_plus_vector))

    grid_seg.section("Opposite directions")
    grid_seg.fact(*[Opposite(dir1=a, dir2=b) for a, b in OPPOSITES])

    # --- Clues ---
    clues = program.add_segment("Clues")
    clues.section("Define numbered endpoints")
    clues.fact(*[Symbol(loc=Cell(row=r, col=c), sym=sym) for r, c, sym in _parse_endpoints(GRID)])

    # --- Rules ---
    rules = program.add_segment("Rules")
    rules.section("Identify cells with symbols")
    rules.when(Symbol(loc=Cell_, sym=ANY)).derive(HasSymbol(loc=Cell_))

    rules.section("Path degree requirements")
    rules.when(HasSymbol(loc=Cell_)).derive(PathDegree(loc=Cell_, degree=1))
    rules.when(cell, ~HasSymbol(loc=cell)).derive(PathDegree(loc=cell, degree=2))

    rules.section("Path choice constraints")
    rules.when(PathDegree(loc=cell, degree=N)).derive(
        Choice(
            element=Path(loc=cell, direction=D),
            condition=OrthogonalDir(cell1=cell, direction=D, cell2=ANY),
        ).exactly(N)
    )

    rules.section("Bidirectional path constraint")
    rules.when(
        Path(loc=Cell1, direction=D),
        OrthogonalDir(cell1=Cell1, direction=D, cell2=Cell2),
        Opposite(dir1=D, dir2=OppD),
    ).derive(Path(loc=Cell2, direction=OppD))

    rules.section("Symbol propagation")
    rules.when(Symbol(loc=Cell_, sym=Sym)).derive(PropagatedSymbol(loc=Cell_, sym=Sym))
    rules.when(
        PropagatedSymbol(loc=Cell1, sym=Sym),
        Path(loc=Cell1, direction=D),
        OrthogonalDir(cell1=Cell1, direction=D, cell2=Cell2),
    ).derive(PropagatedSymbol(loc=Cell2, sym=Sym))

    rules.section("Symbols cannot be connected to different symbols")
    rules.when(Symbol(loc=Cell_, sym=ANY)).require(Count(Sym, condition=PropagatedSymbol(loc=Cell_, sym=Sym)) == 1)

    rules.section("Define connected relationship")
    rules.when(
        Path(loc=Cell1, direction=D),
        OrthogonalDir(cell1=Cell1, direction=D, cell2=Cell2),
    ).derive(Connected(loc1=Cell1, loc2=Cell2))

    rules.section("No self-touch constraint")
    rules.forbid(
        OrthogonalDir(cell1=Cell1, direction=ANY, cell2=Cell2),
        PropagatedSymbol(loc=Cell1, sym=Sym),
        PropagatedSymbol(loc=Cell2, sym=Sym),
        ~Connected(loc1=Cell1, loc2=Cell2),
    )

    rules.section("Solution extraction")
    rules.when(
        cell,
        ~HasSymbol(loc=cell),
        Path(loc=cell, direction=D1),
        Path(loc=cell, direction=D2),
        D1 < D2,
    ).derive(CellDirections(loc=cell, dir1=D1, dir2=D2))

    return program, CellDirections


def test_numberlink_solves_to_the_known_solution() -> None:
    program, CellDirections = _build_program()

    # The reproduced program is a valid clingo program; the autouse conftest
    # fixture parse-checks the render for us.
    rendered = program.render()
    assert "#show cell_directions/3." in rendered

    models = list(program.solve())
    assert len(models) == 1, f"expected a unique Numberlink solution, got {len(models)} models"

    solved = {
        (
            atom["loc"]["row"].value,
            atom["loc"]["col"].value,
            atom["dir1"].value,
            atom["dir2"].value,
        )
        for atom in models[0].atoms(CellDirections)
    }

    expected = _parse_expected(EXPECTED_CELL_DIRECTIONS)
    assert len(expected) == 63
    assert len(solved) == 63
    assert solved == expected
