# Walkthrough: Numberlink

*The second worked example: a real 9×9 puzzle solved end to end — nested terms, recursion, data-driven choices — bridging the tutorial to the Guide.*

This page assumes [Your First Program](getting-started.md): the verbs are the
same — `fact`, `when().derive()`, `Choice`, `forbid`, solve and read back — and
none of them are re-explained here. What's new is scale and technique: nested
terms, rule-generated data, a data-driven choice, a recursive derivation, an
aggregate guard, and validated read-back. Like the tutorial, the whole page is
one continuous runnable script, and the same program is pinned end to end by
the test suite in CI.

## The puzzle

Numberlink: a 9×9 grid holds nine pairs of numbered endpoints. Draw orthogonal
paths joining each number to its twin so that every empty cell is used by
exactly one path, and no path ever runs alongside itself or touches a rival.

The puzzle instance is a Python list of strings — plain data, exactly the
dynamic-program headline from the tutorial. Swap in another grid and nothing
else on this page changes.

```python
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
```

## Cells as values

Here is the whole predicate inventory. The headline is `Cell`: a predicate
used as a *value*. Every other predicate that talks about a grid position
takes `loc: Field[Cell]`, so positions travel as one typed compound term —
`cell(row, col)` — instead of parallel `row`/`col` columns repeated across a
dozen schemas. Predicate-valued fields are declared like any other
[field](predicates.md#declaring-predicates); the rendered form is a
[nested function term](clingo-map.md#terms-and-literals).

```python
from aspalchemy import (
    ANY,
    ASPProgram,
    Choice,
    Count,
    ExplicitPool,
    Field,
    Predicate,
    RangePool,
    Variable,
)

class Cell(Predicate, show=False):
    """A grid position - used as a value inside other predicates."""
    row: Field[int]
    col: Field[int]

class Direction(Predicate, show=False):
    """A compass direction and its offset vector, stored as a Cell."""
    name: Field[str]
    vector: Field[Cell]

class OrthogonalDirections(Predicate, show=False):
    """A direction a path is allowed to use."""
    name: Field[str]

class OrthogonalDir(Predicate, show=False):
    """cell2 is one step from cell1 in the given direction."""
    cell1: Field[Cell]
    direction: Field[str]
    cell2: Field[Cell]

class Opposite(Predicate, show=False):
    """dir2 points back along dir1."""
    dir1: Field[str]
    dir2: Field[str]

class Symbol(Predicate, show=False):
    """A numbered endpoint from the clue grid."""
    loc: Field[Cell]
    sym: Field[int]

class HasSymbol(Predicate, show=False):
    """The cell holds some endpoint."""
    loc: Field[Cell]

class PathDegree(Predicate, show=False):
    """How many path exits the cell must have."""
    loc: Field[Cell]
    degree: Field[int]

class Path(Predicate, show=False):
    """The solver's decision: a path exit from loc in a direction."""
    loc: Field[Cell]
    direction: Field[str]

class PropagatedSymbol(Predicate, show=False):
    """The endpoint symbol reachable from loc along chosen paths."""
    loc: Field[Cell]
    sym: Field[int]

class Connected(Predicate, show=False):
    """loc1 and loc2 are joined by a chosen path step."""
    loc1: Field[Cell]
    loc2: Field[Cell]

class CellDirections(Predicate):
    """The solution: the two exit directions of each path cell."""
    loc: Field[Cell]
    dir1: Field[str]
    dir2: Field[str]
```

A `Symbol` atom renders with its position nested inside it, one term:

```text
symbol(cell(2, 5), 7).
```

Note the shown/hidden split, same policy as the tutorial: every scaffolding
predicate is `show=False`; only `CellDirections` — the shape of the solution —
reaches the model. Class syntax is a choice, not a requirement: the same
schemas can be built at runtime with `Predicate.define`, and they are the
[same objects](predicates.md#dynamic-predicates). Class syntax buys the typed
nested read-back we cash in at the end: `atom.loc.row` will be a plain `int`.

## Build the board with rules

A program this size wants structure, so we build it in named
[segments](rules.md#organizing-output) with `section()` headers — they render
as comment banners and keep the generated ASP navigable.

The first rule is the receipts moment of the page. The tutorial wrote every
fact by hand; here one rule derives all 81 cells from two
[ranges](rules.md#pools-and-ranges):

```python
program = ASPProgram()

R, C = Variable("R"), Variable("C")

grid = program.add_segment("grid")
grid.section("Define cells in the grid")
grid.when(R.in_(RangePool(1, 9)), C.in_(RangePool(1, 9))).derive(Cell(row=R, col=C))

assert "cell(R, C) :- R = 1..9, C = 1..9." in program.render()
```

One rendered line, 81 atoms of intent:

```text
cell(R, C) :- R = 1..9, C = 1..9.
```

## Directions from Python data

Three techniques on one screen. First, the eight compass directions live in a
Python table, and a list comprehension turns the table into facts — the
tutorial's `fact()` pattern, driven by a data structure. Each offset vector is
stored as a nested `Cell(row=dr, col=dc)` value: `Cell` doesn't care that
these "positions" are really displacements.

```python
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

grid.section("Define directions in the grid")
grid.fact(*[Direction(name=name, vector=Cell(row=dr, col=dc)) for name, (dr, dc) in DIRECTION_VECTORS])
```

Second, a [pool](rules.md#pools-and-ranges) inside a fact argument: paths may
only use the four orthogonal directions, and one fact with an `ExplicitPool`
expands to all four.

```python
grid.section("Orthogonal directions")
grid.fact(OrthogonalDirections(name=ExplicitPool(["n", "e", "s", "w"])))

assert 'orthogonal_directions("n"; "e"; "s"; "w").' in program.render()
```

```text
orthogonal_directions("n"; "e"; "s"; "w").
```

Third, the adjacency rule, with two new moves in it. Field values can hold
[arithmetic](math.md) expressions — `Cell(row=R + R_vec, col=C + C_vec)` is
the neighbouring cell, computed in the rule. And atoms are
[values](predicates.md#atoms-as-values): we build `Cell(row=R, col=C)` once,
bind it to a Python name, and reuse the template in rule after rule for the
rest of the page.

```python
cell = Cell(row=R, col=C)

R_vec, C_vec = Variable("R_vec"), Variable("C_vec")
D = Variable("D")

grid.section("Orthogonal adjacency with direction definition")
cell_plus_vector = Cell(row=R + R_vec, col=C + C_vec)
grid.when(
    cell,
    OrthogonalDirections(name=D),
    Direction(name=D, vector=Cell(row=R_vec, col=C_vec)),
    cell_plus_vector,
).derive(OrthogonalDir(cell1=cell, direction=D, cell2=cell_plus_vector))
```

Requiring `cell_plus_vector` in the body keeps the adjacency on the board:
`cell(10, 5)` is never derived, so steps off the edge never ground. `Opposite`
facts close the section — we'll need them to make paths bidirectional.

```python
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

grid.section("Opposite directions")
grid.fact(*[Opposite(dir1=a, dir2=b) for a, b in OPPOSITES])
```

## Load the clues

A five-line parse of `GRID`, then one `fact()` call. Nothing here is new, and
that's the point: parsing and iteration are Python's job, logic is ASP's job,
and the boundary between them is a comprehension wide — exactly where it
should be.

```python
endpoints = [
    (r, c, int(ch))
    for r, line in enumerate(GRID, start=1)
    for c, ch in enumerate(line, start=1)
    if ch.isdigit()
]

clues = program.add_segment("Clues")
clues.section("Define numbered endpoints")
clues.fact(*[Symbol(loc=Cell(row=r, col=c), sym=sym) for r, c, sym in endpoints])

assert "symbol(cell(2, 5), 7)." in program.render()
```

## Degrees: one exit or two

The core observation of the Numberlink model: an endpoint has exactly one
path exit, and every other cell — since every cell must be used — has exactly
two (a path passes through). First we flag the endpoint cells, then we assign
degrees. The second degree rule uses
[default negation](rules.md#default-negation): `~HasSymbol(loc=cell)` reads
"unless the cell is known to hold a number".

```python
Cell_, Sym = Variable("Cell"), Variable("Sym")

rules = program.add_segment("Rules")
rules.section("Identify cells with symbols")
rules.when(Symbol(loc=Cell_, sym=ANY)).derive(HasSymbol(loc=Cell_))

rules.section("Path degree requirements")
rules.when(HasSymbol(loc=Cell_)).derive(PathDegree(loc=Cell_, degree=1))
rules.when(cell, ~HasSymbol(loc=cell)).derive(PathDegree(loc=cell, degree=2))
```

```text
has_symbol(Cell) :- symbol(Cell, _).
path_degree(Cell, 1) :- has_symbol(Cell).
path_degree(cell(R, C), 2) :- cell(R, C), not has_symbol(cell(R, C)).
```

## Choose the paths

One [choice rule](choices-and-aggregates.md#choice-rules) makes every decision
in this program. The tutorial's choice was
[`.exactly(1)`](getting-started.md#choose-exactly-one-color) with a literal
cardinality; here the cardinality is `.exactly(N)` with `N` bound in the body
— the *data* decides how many exits each cell gets, so one rule covers both
endpoints (degree 1) and path cells (degree 2).

```python
N = Variable("N")

rules.section("Path choice constraints")
rules.when(PathDegree(loc=cell, degree=N)).derive(
    Choice(
        element=Path(loc=cell, direction=D),
        condition=OrthogonalDir(cell1=cell, direction=D, cell2=ANY),
    ).exactly(N)
)

assert (
    "{ path(cell(R, C), D) : orthogonal_dir(cell(R, C), D, _) } = N :- path_degree(cell(R, C), N)."
    in program.render()
)
```

```text
{ path(cell(R, C), D) : orthogonal_dir(cell(R, C), D, _) } = N :- path_degree(cell(R, C), N).
```

Read it aloud, tutorial-style: for each cell with path degree `N`, choose
exactly `N` `path` atoms, drawing the direction `D` only from directions that
actually lead to a neighbouring cell — so edge cells can never point off the
board.

## Recursion: propagate and connect

Three derivations give the chosen exits their meaning, and two of them are
recursive — the head predicate appears in its own body. In Python this would
be a worklist algorithm with a visited set; in ASP it is just a rule, and the
solver handles saturation and termination. First, paths are bidirectional: an
exit from `Cell1` towards `Cell2` derives the matching exit back. Then each
endpoint's symbol flood-fills along the chosen paths, and any path step
connects its two cells.

```python
OppD = Variable("OppD")
Cell1, Cell2 = Variable("Cell1"), Variable("Cell2")

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

rules.section("Define connected relationship")
rules.when(
    Path(loc=Cell1, direction=D),
    OrthogonalDir(cell1=Cell1, direction=D, cell2=Cell2),
).derive(Connected(loc1=Cell1, loc2=Cell2))
```

```text
path(Cell2, OppD) :- path(Cell1, D), orthogonal_dir(Cell1, D, Cell2), opposite(D, OppD).
propagated_symbol(Cell, Sym) :- symbol(Cell, Sym).
propagated_symbol(Cell2, Sym) :- propagated_symbol(Cell1, Sym), path(Cell1, D), orthogonal_dir(Cell1, D, Cell2).
connected(Cell1, Cell2) :- path(Cell1, D), orthogonal_dir(Cell1, D, Cell2).
```

## Guard with an aggregate

Degrees alone don't stop two different numbers' paths from fusing into one
snake. The fix: every endpoint must see *exactly one* propagated symbol.
That's a `Count` in a comparison — a
[guard](choices-and-aggregates.md#guards-the-right-way) — closed with
`require()`, the positive spelling of `forbid` among
[the verbs](rules.md#the-verbs): state what must hold, and it renders as a
constraint against the complement. One-sided guard, one comparison — the
guards page explains why that shape matters.

```python
rules.section("Symbols cannot be connected to different symbols")
rules.when(Symbol(loc=Cell_, sym=ANY)).require(
    Count(Sym, condition=PropagatedSymbol(loc=Cell_, sym=Sym)) == 1
)

assert "#count{ Sym : propagated_symbol(Cell, Sym) } != 1." in program.render()
```

```text
:- symbol(Cell, _), #count{ Sym : propagated_symbol(Cell, Sym) } != 1.
```

## Forbid self-touch

The tutorial's `forbid` had two atoms; this is what a production constraint
looks like: four literals mixing positive atoms with a default negation. Read
it aloud: two adjacent cells that carry the same symbol but have no chosen
path step between them are an illegal touch — the path running alongside
itself, which Numberlink forbids.

```python
rules.section("No self-touch constraint")
rules.forbid(
    OrthogonalDir(cell1=Cell1, direction=ANY, cell2=Cell2),
    PropagatedSymbol(loc=Cell1, sym=Sym),
    PropagatedSymbol(loc=Cell2, sym=Sym),
    ~Connected(loc1=Cell1, loc2=Cell2),
)
```

```text
:- orthogonal_dir(Cell1, _, Cell2), propagated_symbol(Cell1, Sym), propagated_symbol(Cell2, Sym), not connected(Cell1, Cell2).
```

## Extract the solution

Each path cell has two exits, and we want them as one atom. Naively deriving
`CellDirections` from two `Path` atoms would emit every pair twice — `(e, w)`
and `(w, e)` — so the body orders the variables with a
[comparison](rules.md#comparisons): `D1 < D2` is a symmetry breaker, keeping
exactly one of the two orderings. This is also where the shown/hidden split
pays off: eleven scaffolding predicates stay internal, and only
`cell_directions/3` reaches the model.

```python
D1, D2 = Variable("D1"), Variable("D2")

rules.section("Solution extraction")
rules.when(
    cell,
    ~HasSymbol(loc=cell),
    Path(loc=cell, direction=D1),
    Path(loc=cell, direction=D2),
    D1 < D2,
).derive(CellDirections(loc=cell, dir1=D1, dir2=D2))
```

```text
cell_directions(cell(R, C), D1, D2) :- cell(R, C), not has_symbol(cell(R, C)), path(cell(R, C), D1), path(cell(R, C), D2), D1 < D2.
```

## Solve and verify

This puzzle has exactly one solution, so we can do something the tutorial
couldn't: assert the model count. Pinning solver output is normally
forbidden — enumeration order isn't stable — but a program with a provably
unique answer set is the exception, and this instance's uniqueness (and its
full 63-atom solution table, which this page checks by property instead) is
pinned by the test suite in CI.

```python
models = list(program.solve())
assert len(models) == 1, f"expected a unique solution, got {len(models)} models"

solved = {
    (atom.loc.row, atom.loc.col, atom.dir1, atom.dir2)
    for atom in models[0].atoms(CellDirections)
}
```

That read-back is the typed-fields payoff on a nested atom: `atom.loc` is a
real `Cell` instance, `atom.loc.row` is a plain `int`, `atom.dir1` a plain
`str` — no unwrapping, straight into a set of tuples
([reading models](solving.md#reading-models),
[the field contract](predicates.md#writes-and-reads); for consuming more than
one model, see [the model stream](solving.md#the-model-stream)).

Now the receipts, checked as *properties* of a valid Numberlink solution —
and note the checks reuse the same Python tables the program was built from:

```python
STEP = {name: vec for name, vec in DIRECTION_VECTORS if name in {"n", "e", "s", "w"}}
OPP = dict(OPPOSITES)
endpoint_cells = {(r, c) for r, c, _ in endpoints}

# (a) Every non-endpoint cell is used: 81 cells minus the endpoints.
assert len(solved) == 9 * 9 - len(endpoint_cells)

# (b) No endpoint has a direction pair - endpoints are path ends, not path cells.
pair_at = {(r, c): frozenset({d1, d2}) for r, c, d1, d2 in solved}
assert endpoint_cells.isdisjoint(pair_at)

# (c) Reciprocity: every exit's neighbour points back, or is an endpoint.
for (r, c), dirs in pair_at.items():
    for d in dirs:
        nr, nc = r + STEP[d][0], c + STEP[d][1]
        assert (nr, nc) in endpoint_cells or OPP[d] in pair_at[(nr, nc)]

# (d) Every endpoint is entered by exactly one neighbouring exit.
for r, c in endpoint_cells:
    entries = sum(
        1
        for d, (dr, dc) in STEP.items()
        if (r + dr, c + dc) in pair_at and OPP[d] in pair_at[(r + dr, c + dc)]
    )
    assert entries == 1
```

## Draw it

The payoff. Each cell's direction pair maps onto a box-drawing character,
endpoints keep their digits, and the paths appear. This is presentation, not
modeling — fifteen lines of ordinary Python consuming the solved set. It is
deterministic by construction (unique model, full grid, row-by-row order), so
showing the picture is safe; the assert pins the load-bearing property.

```python
GLYPHS = {
    frozenset({"n", "s"}): "│",
    frozenset({"e", "w"}): "─",
    frozenset({"n", "e"}): "└",
    frozenset({"n", "w"}): "┘",
    frozenset({"s", "e"}): "┌",
    frozenset({"s", "w"}): "┐",
}
picture = [
    "".join(ch if ch.isdigit() else GLYPHS[pair_at[(r, c)]] for c, ch in enumerate(line, start=1))
    for r, line in enumerate(GRID, start=1)
]
assert all(len(row) == 9 for row in picture)
```

```python
>>> print("\n".join(picture))
┌────┐┌─┐
│┌─┐7│94│
6│3│││┌┘│
┌┘│8│││5│
│3┘67││││
└─8└─┘│││
2────┐│││
┌───1││││
12───┘459
```

## Where next

Every technique above has a home page that teaches it in depth: nested fields
and atom identity in [Predicates and Data](predicates.md), rule shapes,
negation, and pools in [Rules and Terms](rules.md), choices and guard idioms
in [Choices and Aggregates](choices-and-aggregates.md), and model consumption
in [Solving and Results](solving.md). Read the Guide in nav order and it is
the curriculum. And when you want to see this style of modeling
industrialized — a whole framework of grid puzzles built on exactly these
idioms — that's [aspuzzle](https://github.com/jolyonb/aspuzzle).
