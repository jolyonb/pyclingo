# Walkthrough: Numberlink

This page picks up where [Your First Program](getting-started.md) left off. The verbs are the
same — `fact`, `when().derive()`, `Choice`, `forbid`, solve and read back — and we won't explain
them again. What's new is the scale, and the techniques that scale asks for: positions that travel
as a single typed value, rules that generate their own data, a choice whose size the data decides,
recursive derivations, an aggregate guard, and a typed read-back at the end. Like the tutorial, the
whole page is one continuous runnable script, and the same program is run by the test suite on
every commit.

## The puzzle

Numberlink: a 9×9 grid holds nine pairs of numbered endpoints. Draw orthogonal paths joining each
number to its twin so that every empty cell is used by exactly one path, and no path ever runs
alongside itself or touches a rival.

The puzzle instance is a Python list of strings — plain data. This is the tutorial's point about the
data being independent of the logic, in its simplest form: swap in another grid and nothing else on
this page changes.

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

We declare each predicate in the section that first needs it, rather than piling them all up here —
a schema makes more sense next to the rule that motivates it. But one of them has to come first,
because almost everything else is built out of it.

A grid position is two numbers. We could give every predicate that mentions a position its own `row`
and `col` fields — the same pair, repeated across a dozen schemas — but instead we make `Cell` a
predicate that we use as a *value*. Everything that talks about a position then takes a single field
of type `Cell`, and the position travels as one typed compound term, `cell(row, col)`.
Predicate-valued fields are declared like any other
[field](predicates.md#declaring-predicates), and they render as a
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
```

`show=False` is the tutorial's policy again, and on this page nearly every predicate carries it:
all of them are scaffolding except the last one we declare, which describes the answer. Class syntax
isn't a requirement either — the same schemas can be built at runtime with `Predicate.define`, and
they are the [same objects](predicates.md#dynamic-predicates). What class syntax buys us is the
typed read-back we cash in at the end, where `atom.loc.row` will be a plain `int`.

## Build the board with rules

A program this size wants some structure, so we build it in named
[segments](rules.md#organizing-output) with `section()` headers. They render as comment banners, and
they keep the generated ASP navigable when you go looking at it.

The first rule earns the whole section. In the tutorial every fact was data we supplied from
Python; here the board needs no data at all. Two [ranges](rules.md#pools-and-ranges) and a
single rule derive all 81 cells:

```python
program = ASPProgram()

R, C = Variable("R"), Variable("C")

grid = program.add_segment("grid")
grid.section("Define cells in the grid")
grid.when(R.in_(RangePool(1, 9)), C.in_(RangePool(1, 9))).derive(Cell(row=R, col=C))
```

A segment is iterable, and every statement in it can render itself, so we can print exactly the line
we just added:

```python
>>> print(list(grid)[-1].render())
cell(R, C) :- R = 1..9, C = 1..9.
```

One line of ASP, and 81 atoms once the grounder gets to it.

## Directions from Python data

This section needs four predicates. Two of them are where `Cell`-as-a-value starts earning its keep:
`Direction` stores an offset *vector* in a `Cell` field, and `OrthogonalDir` relates two positions
that are one step apart. The other two are plain tables of direction names.

```python
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
```

A `Direction` atom therefore carries a whole position inside itself, as a single nested term:

```python
>>> Direction(name="n", vector=Cell(row=-1, col=0)).render()
'direction("n", cell(-1, 0))'
```

Now three things happen, and each of them is a way of letting Python do work that ASP shouldn't have
to.

First, the eight compass directions live in a Python table, and a comprehension turns that table
into facts — the tutorial's `fact()` pattern again, driven by a data structure rather than typed out
by hand. Each offset vector is stored as a nested `Cell(row=dr, col=dc)` value: `Cell` doesn't care
that these "positions" are really displacements, because a pair of ints is a pair of ints.

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

Second, a [pool](rules.md#pools-and-ranges) inside a fact's argument. Paths may only use the four
orthogonal directions, and rather than write four facts we write one, with an `ExplicitPool` that
expands into all four:

```python
grid.section("Orthogonal directions")
grid.fact(OrthogonalDirections(name=ExplicitPool(["n", "e", "s", "w"])))
```

```python
>>> print(list(grid)[-1].render())
orthogonal_directions("n"; "e"; "s"; "w").
```

Third, the adjacency rule, which brings in two moves we'll lean on for the rest of the page. Field
values can hold [arithmetic](math.md) expressions, so `Cell(row=R + R_vec, col=C + C_vec)` names the
neighbouring cell and leaves the addition to the grounder. And atoms are
[values](predicates.md#atoms-as-values), so we can build `Cell(row=R, col=C)` once, bind it to the
Python name `cell`, and reuse that template in rule after rule for the rest of the page.

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

Requiring `cell_plus_vector` in the body is what keeps adjacency on the board. There is no
`cell(10, 5)` to match, so a step off the edge simply never grounds — we don't have to say anything
about boundaries, we just decline to invent cells that aren't there. The `Opposite` facts close the
section; we need them shortly, to make paths run both ways.

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

A clue is a number sitting at a position, which is one predicate:

```python
class Symbol(Predicate, show=False):
    """A numbered endpoint from the clue grid."""
    loc: Field[Cell]
    sym: Field[int]
```

Then a short comprehension to parse the grid, and one `fact()` call. Nothing here is new, and that
is the point:
parsing and iteration are Python's job, the logic is ASP's job, and the boundary between them is one
comprehension wide.

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
```

Eighteen endpoints become eighteen facts, and the `section()` header renders as the comment banner
above them:

```python
>>> print(clues.render())

% Define numbered endpoints
symbol(cell(2, 5), 7).
symbol(cell(2, 7), 9).
symbol(cell(2, 8), 4).
symbol(cell(3, 1), 6).
symbol(cell(3, 3), 3).
symbol(cell(4, 4), 8).
symbol(cell(4, 8), 5).
symbol(cell(5, 2), 3).
symbol(cell(5, 4), 6).
symbol(cell(5, 5), 7).
symbol(cell(6, 3), 8).
symbol(cell(7, 1), 2).
symbol(cell(8, 5), 1).
symbol(cell(9, 1), 1).
symbol(cell(9, 2), 2).
symbol(cell(9, 7), 4).
symbol(cell(9, 8), 5).
symbol(cell(9, 9), 9).
```

## One exit or two

This is the observation the whole model rests on, and it's worth getting straight before reading the
rules. In a finished grid every cell is used by a path, and a path either *ends* at a cell or
*passes through* it. A cell holding a number is where a path ends, so it has exactly one exit. Every
other cell is passed through, so it has exactly two — one in, one out.

Two predicates record that: which cells hold a number, and what degree each cell must have.

```python
class HasSymbol(Predicate, show=False):
    """The cell holds some endpoint."""
    loc: Field[Cell]

class PathDegree(Predicate, show=False):
    """How many path exits the cell must have."""
    loc: Field[Cell]
    degree: Field[int]
```

So we flag the cells that hold numbers, and then assign each cell its degree. The second degree rule
uses [default negation](rules.md#default-negation): `~HasSymbol(loc=cell)` reads as *unless this
cell is known to hold a number*.

```python
Cell_, Sym = Variable("Cell"), Variable("Sym")

rules = program.add_segment("Rules")
rules.section("Identify cells with symbols")
rules.when(Symbol(loc=Cell_, sym=ANY)).derive(HasSymbol(loc=Cell_))

rules.section("Path degree requirements")
rules.when(HasSymbol(loc=Cell_)).derive(PathDegree(loc=Cell_, degree=1))
rules.when(cell, ~HasSymbol(loc=cell)).derive(PathDegree(loc=cell, degree=2))
```

```python
>>> print(rules.render())

% Identify cells with symbols
has_symbol(Cell) :- symbol(Cell, _).

% Path degree requirements
path_degree(Cell, 1) :- has_symbol(Cell).
path_degree(cell(R, C), 2) :- cell(R, C), not has_symbol(cell(R, C)).
```

## Choose the paths

Here is the one thing in this program the solver actually gets to decide, and so it gets a predicate
of its own: a path leaving a cell in some direction.

```python
class Path(Predicate, show=False):
    """The solver's decision: a path exit from loc in a direction."""
    loc: Field[Cell]
    direction: Field[str]
```

Every decision in this program is made by one choice rule over that predicate. In the tutorial the
cardinality was a literal — [`.exactly(1)`](getting-started.md#choose-exactly-one-color), one color
per state. Here it is `.exactly(N)`, with `N` bound in the body, so the *data* decides how many
exits a cell gets: the same rule covers endpoints (degree 1) and path cells (degree 2), and we never
write the two cases out separately.

```python
N = Variable("N")

rules.section("Path choice constraints")
rules.when(PathDegree(loc=cell, degree=N)).derive(
    Choice(
        element=Path(loc=cell, direction=D),
        condition=OrthogonalDir(cell1=cell, direction=D, cell2=ANY),
    ).exactly(N)
)
```

```python
>>> print(list(rules)[-1].render())
{ path(cell(R, C), D) : orthogonal_dir(cell(R, C), D, _) } = N :- path_degree(cell(R, C), N).
```

Read it as we read the tutorial's choice. For each cell with path degree `N`, the solver must make
exactly `N` `path` atoms true for that cell — and the `condition=` supplies the menu it chooses
from, which here is the directions that actually lead somewhere. An edge cell has fewer neighbours,
so it has fewer options, and it can never choose to point off the board.

## Propagate and connect, recursively

Three derivations give the chosen exits their meaning, and two of them are *recursive*: the
predicate in the head also appears in the body. In Python this would be a worklist and a visited
set. In ASP it is just a rule — the solver works out how far the derivation reaches and when there
is nothing left to add.

Two of the three derive new predicates, so we declare those first: the symbol a cell can be reached
from, and the fact that two cells are joined.

```python
class PropagatedSymbol(Predicate, show=False):
    """The endpoint symbol reachable from loc along chosen paths."""
    loc: Field[Cell]
    sym: Field[int]

class Connected(Predicate, show=False):
    """loc1 and loc2 are joined by a chosen path step."""
    loc1: Field[Cell]
    loc2: Field[Cell]
```

First, paths run both ways: an exit from `Cell1` towards `Cell2` derives the matching exit back from
`Cell2`. Then each endpoint's symbol flood-fills along the chosen path — that's the recursive one,
and it's what lets us ask, later, which number a given cell belongs to. Finally, any chosen step
records the two cells it joins.

```python
OppD = Variable("OppD")
Cell1, Cell2 = Variable("Cell1"), Variable("Cell2")

mark = len(rules)  # where the segment ends now, so we can print just what follows

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

```python
>>> print("\n".join(statement.render() for statement in list(rules)[mark:]))

% Bidirectional path constraint
path(Cell2, OppD) :- path(Cell1, D), orthogonal_dir(Cell1, D, Cell2), opposite(D, OppD).

% Symbol propagation
propagated_symbol(Cell, Sym) :- symbol(Cell, Sym).
propagated_symbol(Cell2, Sym) :- propagated_symbol(Cell1, Sym), path(Cell1, D), orthogonal_dir(Cell1, D, Cell2).

% Define connected relationship
connected(Cell1, Cell2) :- path(Cell1, D), orthogonal_dir(Cell1, D, Cell2).
```

## Guard with an aggregate

Degrees alone don't finish the job. Two different numbers' paths could fuse into one long snake and
every cell would still have exactly the right number of exits — the count is satisfied, the puzzle
is not. What rules that out is this: every endpoint must see *exactly one* propagated symbol.

That is a `Count` compared against a number, the shape we met in the tutorial, except that we close
it with `require()` rather than `forbid()`. `require()` is the positive spelling among
[the verbs](rules.md#the-verbs): we say what must hold, and the library writes the constraint that
forbids the opposite. Which is why the Python below says `== 1` and the ASP it renders says `!= 1` —
the same statement, seen from the two sides. (A `Count` in a comparison like this is called a
[guard](choices-and-aggregates.md#guards-the-right-way), and the shape matters: one comparison, one
side.)

```python
rules.section("Symbols cannot be connected to different symbols")
rules.when(Symbol(loc=Cell_, sym=ANY)).require(
    Count(Sym, condition=PropagatedSymbol(loc=Cell_, sym=Sym)) == 1
)
```

```python
>>> print(list(rules)[-1].render())
:- symbol(Cell, _), #count{ Sym : propagated_symbol(Cell, Sym) } != 1.
```

## Forbid self-touch

The tutorial's border constraint took three plain atoms. This is what one looks like in earnest:
four literals, mixing positive atoms with a default negation. Read it as a single sentence — two
neighbouring cells that carry the same symbol, but with no chosen path step between them, are an
illegal touch. That is the path running alongside itself, which Numberlink does not allow.

```python
rules.section("No self-touch constraint")
rules.forbid(
    OrthogonalDir(cell1=Cell1, direction=ANY, cell2=Cell2),
    PropagatedSymbol(loc=Cell1, sym=Sym),
    PropagatedSymbol(loc=Cell2, sym=Sym),
    ~Connected(loc1=Cell1, loc2=Cell2),
)
```

```python
>>> print(list(rules)[-1].render())
:- orthogonal_dir(Cell1, _, Cell2), propagated_symbol(Cell1, Sym), propagated_symbol(Cell2, Sym), not connected(Cell1, Cell2).
```

## Extract the solution

The last predicate is the answer itself, and it is the only one on the page that we let out: no
`show=False` here.

```python
class CellDirections(Predicate):
    """The solution: the two exit directions of each path cell."""
    loc: Field[Cell]
    dir1: Field[str]
    dir2: Field[str]
```

Each path cell has two exits, and we want them together in one atom. Deriving `CellDirections` from
two `Path` atoms naively would give us every pair twice, once as `(e, w)` and once as `(w, e)`,
because nothing says which of the two exits comes first. So the body orders them with a
[comparison](rules.md#comparisons): `D1 < D2` keeps one of the two orderings and discards its
mirror.

This is where the shown/hidden split pays off. Eleven scaffolding predicates stay internal, and only
`cell_directions/3` reaches the model — so what comes back from a solve is the solution, and nothing
else.

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

```python
>>> print(list(rules)[-1].render())
cell_directions(cell(R, C), D1, D2) :- cell(R, C), not has_symbol(cell(R, C)), path(cell(R, C), D1), path(cell(R, C), D2), D1 < D2.
```

## Solve and verify

This puzzle has exactly one solution, which lets us do something the tutorial could not: assert how
many models there are. Pinning solver output is normally a bad idea, because enumeration order isn't
stable — but a program with a provably unique answer set is the exception, and it's what allows the
picture at the end of this page to be a doctest.

```python
models = list(program.solve())
assert len(models) == 1, f"expected a unique solution, got {len(models)} models"

solved = {
    (atom.loc.row, atom.loc.col, atom.dir1, atom.dir2)
    for atom in models[0].atoms(CellDirections)
}
```

That read-back is the typed-field payoff, on a nested atom: `atom.loc` is a real `Cell` instance,
`atom.loc.row` is a plain `int`, and `atom.dir1` is a plain `str`. Nothing needs unwrapping, so the
model goes straight into a set of tuples ([reading models](solving.md#reading-models),
[the field contract](predicates.md#writes-and-reads); for consuming more than one model, see
[the model stream](solving.md#the-model-stream)).

Now the checks. Rather than pin the answer, they assert the properties that make an answer a valid
Numberlink solution — and note that they reuse the very Python tables the program was built from:

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

And now the payoff. Each cell's pair of directions maps onto a box-drawing character, the endpoints
keep their digits, and the paths appear. This is presentation rather than modelling — a dozen lines
of ordinary Python, consuming the set we solved for. It is deterministic by construction (one model,
a full grid, taken row by row), so the picture below is a doctest too: CI checks the drawing, cell
for cell.

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

Every technique on this page has a home page that teaches it properly: nested fields and atom
identity in [Predicates and Data](predicates.md); rule shapes, negation and pools in
[Rules and Terms](rules.md); choices and guard idioms in
[Choices and Aggregates](choices-and-aggregates.md); and model consumption in
[Solving and Results](solving.md). Read the Guide in nav order and it is a curriculum. And when you
want to see this style of modelling industrialized — a whole framework of grid puzzles built on
exactly these idioms — that is [aspuzzle](https://github.com/jolyonb/aspuzzle).
