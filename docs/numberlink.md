# Walkthrough: Numberlink

Having seen [a simple program](getting-started.md), we're now going to build a more complicated
one that solves a nontrivial puzzle. The mechanics here are all the same as before, but we're
going to lean much harder on creating logical rules and definitions than in the previous tutorial.
Like before, the whole page is one continuous runnable script, and we encourage you to follow
along.

## Numberlink puzzles

A grid holds pairs of numbered endpoints. Draw orthogonal paths joining each
number to its twin so that every empty cell is used by exactly one path. Paths cannot cross each
other, and a path cannot touch itself orthogonally (so if two adjacent cells are part of the same
path, they must be connected).

To make the puzzle concrete, here is a specific solving grid, as a python list of strings:

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

A grid position is two numbers. We could give every predicate that mentions a position its own `row`
and `col` fields — the same pair, repeated across a dozen schemas — but instead we make `Cell` a
predicate that we use as a *value*. Everything that talks about a position then takes a single field
of type `Cell`, and the position travels as one typed compound term. Predicate-valued fields are
declared like any other [field](predicates.md#declaring-predicates), and they render as a
[nested function term](clingo-map.md#terms-and-literals).

```python
from aspalchemy import (
    ANY,
    ASPProgram,
    Choice,
    Count,
    Field,
    Predicate,
    RangePool,
    Variable,
)

class Cell(Predicate, show=False):
    """A grid position."""
    row: Field[int]
    col: Field[int]
```

`show=False` is the tutorial's policy again, and on this page nearly every predicate carries it:
all of them are scaffolding except the last one we declare, which describes the answer.

## Describe the grid

Before we get to describing the rules of the puzzle, we need to describe the grid that it operates
on. The first question we need to answer is "which cells exist?", and we define `cell` atoms for
each cell in the grid. Two [ranges](statements.md#pools-and-ranges) and a single rule derive every one of
them:

```python
program = ASPProgram()

R, C = Variable("R"), Variable("C")
rows = program.define_constant("rows", len(GRID))
cols = program.define_constant("cols", len(GRID[0]))

program.section("Set up the grid")
program.comment("Every cell in the grid")
program.when(R.in_(RangePool(1, rows)), C.in_(RangePool(1, cols))).derive(Cell(row=R, col=C))
```

`define_constant()` declares a `#const` in the generated program and hands back a term you can use
anywhere a number would go. Both are measured off `GRID` rather than typed in, so the board's shape
is stated exactly once, in the puzzle data — and the rule is written in terms of `rows` and `cols`.

Next, we describe the geometry of the grid, in terms of the displacements between neighboring cells.

```python
DIRECTION_VECTORS = [
    ("n", (-1, 0)),
    ("e", (0, 1)),
    ("s", (1, 0)),
    ("w", (0, -1)),
]

class Direction(Predicate, show=False):
    """A compass direction and its offset vector, stored as a Cell."""
    name: Field[str]
    vector: Field[Cell]

program.comment("The four directions a path may travel, and the step each one takes")
program.fact(*[Direction(name=name, vector=Cell(row=dr, col=dc)) for name, (dr, dc) in DIRECTION_VECTORS])
```

Each offset vector is stored as a nested `Cell(row=dr, col=dc)` value: `Cell` doesn't care that
these "positions" are really displacements, because a pair of ints is a pair of ints.

We also need to know which directions are opposites of each other. ASP will ask this question from
both ends — one rule wants the reverse of "n", another the reverse of "s" — so it needs a fact each
way. We only have to say it once: the axes are the data, and Python fills in both orderings.

```python
OPPOSITE_AXES = [("n", "s"), ("e", "w")]

class Opposite(Predicate, show=False):
    """dir1 and dir2 point in opposite directions."""
    dir1: Field[str]
    dir2: Field[str]

program.comment("Which directions are opposite of each other")
program.fact(*[
    Opposite(dir1=a, dir2=b)
    for one, other in OPPOSITE_AXES
    for a, b in ((one, other), (other, one))
])
```

Now that we're armed with the grid geometry, we can ask which cells are adjacent to each other, and
in which direction. This brings in two moves we'll lean on for the rest of the page. Field values
can hold [arithmetic](math.md) expressions, so `Cell(row=R + DR, col=C + DC)` names the neighboring
cell. And atoms are [values](predicates.md#predicate-instances-as-python-values), so we can build `Cell(row=R, col=C)`
once, bind it to the Python name `cell`, and reuse that template in rule after rule for the rest of
the page.

```python
D, DR, DC = Variable("D"), Variable("DR"), Variable("DC")
cell = Cell(row=R, col=C)
cell_plus_vector = Cell(row=R + DR, col=C + DC)

class Adjacent(Predicate, show=False):
    """cell2 is one step from cell1 in the given direction."""
    cell1: Field[Cell]
    cell2: Field[Cell]
    direction: Field[str]

program.comment("Two cells are adjacent when a direction leads from one to the other")
program.when(
    cell,
    Direction(name=D, vector=Cell(row=DR, col=DC)),
    cell_plus_vector,
).derive(Adjacent(cell1=cell, direction=D, cell2=cell_plus_vector))
```

The rule here specifies that:
* For each cell(R, C)
* and each direction D with step (DR, DC)
* if the neighboring cell(R + DR, C + DC) also exists
* then specify that the two cells are Adjacent with the given direction.

That third line is doing more than it looks. It is the only thing standing between us and steps off
the edge of the board — and we never had to write a boundary condition to get it. A cell in the top
row has no northern neighbor because there is no `cell(0, 5)` for the rule to match, so the
adjacency simply doesn't exist. We didn't forbid the edge of the board; we just declined to invent
cells that aren't there.

## Load the clues

Now that the grid is fully defined, we need to specify the clues that the puzzle provides. This
comes in the form of a single predicate, which says "this cell has this number". A clue cell is
also an *endpoint* — where a path begins or ends — and we'll use the two words interchangeably
from here on.

```python
class Clue(Predicate, show=False):
    """A numbered endpoint the puzzle gives us."""
    loc: Field[Cell]
    number: Field[int]

clues = [
    Clue(loc=Cell(row=r, col=c), number=int(ch))
    for r, line in enumerate(GRID, start=1)
    for c, ch in enumerate(line, start=1)
    if ch.isdigit()
]

program.section("Clues")
program.fact(*clues)
```

Of note here is that we've succinctly converted the grid representation from a list of strings into
ASP facts using a small list comprehension. Eighteen endpoints become eighteen facts.

At this stage, we're done specifying the structure that the puzzle gave us. Now it's time to start
specifying the rules of the puzzle.

## Choose the paths

We're going to model the paths in the solution as a series of path segments, with each segment
connecting two cells. Cells with a number clue in them will have one path segment, while cells
without numbers will need two: one for each direction the path takes from that cell. We'll also need
to demand that if Cell A has a path segment that points to Cell B, then Cell B has a path segment
pointing to Cell A.

Let's start by defining the choices that the solver gets to make.

```python
class PathSegment(Predicate, show=False):
    """The solver's decision: a path exit from loc in a direction."""
    loc: Field[Cell]
    direction: Field[str]

exits = Choice(
    element=PathSegment(loc=cell, direction=D),
    condition=Adjacent(cell1=cell, direction=D, cell2=ANY),
)

program.section("The rules")
program.comment("An endpoint gets one path exit")
program.when(Clue(loc=cell, number=ANY)).derive(exits.exactly(1))

program.section("All other cells get two path exits")
program.when(cell, ~Clue(loc=cell, number=ANY)).derive(exits.exactly(2))
```

We've specified two rules here. The first is for clues — each clue cell gets to choose one path
segment, while each cell that is NOT a clue must choose two. For the choice menus, we allow for
choosing any direction that leads to an adjacent cell. Note that we previously defined `Adjacent`
to connect cells in the grid, so this will never choose a path segment that would leave the grid.

The use of `ANY` here is interesting: we use it to discard information. We don't care what number
is (or is not) in a cell, and we don't care what the adjacent cell is in the menu. Note that we
also snuck in a negation here. `~Clue(loc=cell, number=ANY)` is
[default negation](statements.md#default-negation): it is not an atom we assert, it is a *condition on
the body*, and it holds for a cell precisely when no `Clue` atom mentions it. So the second rule
fires exactly for the cells with no number on them — the empty cells, which get two exits.

We now impose the condition that if Cell A connects to Cell B, then the opposite connection must
also be present.

```python
OppD = Variable("OppD")

program.section("If Cell A has a path segment pointing to Cell B, then Cell B has a path segment pointing to Cell A")
program.when(
    PathSegment(loc=C[1], direction=D),
    Adjacent(cell1=C[1], cell2=C[2], direction=D),
    Opposite(dir1=D, dir2=OppD),
).derive(PathSegment(loc=C[2], direction=OppD))
```

The rule is fairly straightforward: if cell 1 has a path segment pointing in direction D,
which according to the Adjacent predicate maps to cell 2, and the opposite predicate says
that this has direction OppD, then create the path segment in the opposite direction.
We've used a new piece of notation here though. `C[1]` is a shorthand for `Variable("C_1")`,
and `C[2]` is `Variable("C_2")`, so a family of related variables comes from the base you
already have, rather than from minting names by hand. Secondly, `C` is just a variable — we
previously used it to refer to columns, but here we can use it to refer to cells; the meaning
of the variable is scoped to a single rule.

Now that path segments are being chosen, we need to record which cells are being connected
by a path segment.

```python
class Connected(Predicate, show=False):
    """loc1 and loc2 are joined by a chosen path step."""
    loc1: Field[Cell]
    loc2: Field[Cell]

program.section("Two cells are connected if the path steps between them")
program.when(
    PathSegment(loc=C[1], direction=D),
    Adjacent(cell1=C[1], cell2=C[2], direction=D),
).derive(Connected(loc1=C[1], loc2=C[2]))
```

`Connected` carries the same information as `PathSegment`, so why keep both? Because the two forms
are good at different things. `PathSegment` names a *direction*, which is what let us write the
choice rule — the solver picks from a menu of directions. `Connected` throws the direction away and
just relates two cells, which is the shape the propagation rule below wants. And because the
reciprocity rule made path segments run both ways, `Connected` comes out symmetric for free: it
holds both as `Connected(cell_A, cell_B)` and `Connected(cell_B, cell_A)`.

## Propagate numbers and constrain

Now the crux: ensuring each number reaches its twin, and *only* its twin. That is a *global*
property of a whole path, but every rule we can write is *local* — it sees a cell and its neighbors,
not the whole path. The bridge is to let each clue's number spread, cell by connected cell, along
the path it belongs to.

Once numbers spread that way, we can ask a local question of every cell: how many numbers has it
been reached by? In a finished puzzle the answer is always exactly one — a cell lies on exactly one
path, and carries that path's number. Two different things break that. A cell reached by *two*
numbers means that its path connects two different numbers. A cell reached by *none* lies on a
closed loop of empty cells that touches no clue — a legal-looking tangle that belongs to no number's
path. So "every cell sees exactly one number" rules out both at once.

It is tempting to check only the endpoints, since there are far fewer of them, and surely this is
cheaper. However, this would only protect against paths carrying two distinct numbers, but not
loops carrying none. The check has to be on every cell.

```python
class PropagatedNumber(Predicate, show=False):
    """A clue number reachable from loc along chosen paths."""
    loc: Field[Cell]
    number: Field[int]

Num = Variable("Num")

program.section("A cell connected to a cell carrying a number carries that number too")
program.when(Clue(loc=C, number=Num)).derive(PropagatedNumber(loc=C, number=Num))
program.when(
    PropagatedNumber(loc=C[1], number=Num),
    Connected(loc1=C[1], loc2=C[2]),
).derive(PropagatedNumber(loc=C[2], number=Num))
```

Note that there are two rules here. The first simply says that a clue cell propagates itself,
while the second is the recursive constraint: if cell 1 has a number, and cell 1 is connected
to cell 2, then cell 2 also has that number.

Next, we put in place a count constraint: each cell must see exactly one number propagating along
its path. This is our first use of [`require()`](statements.md#the-verbs) — the positive twin of
`forbid()`. Where `forbid()` states what must *never* hold, `require()` states what *must* hold, and
the library turns it into the constraint forbidding the opposite. That is why the Python below reads
`== 1` while the ASP it renders reads `!= 1`: the same rule, stated from the two sides.

```python
program.section("Every cell sees exactly one number: no stray loops, no paths between different numbers")
program.when(cell).require(
    Count(Num, condition=PropagatedNumber(loc=cell, number=Num)) == 1
)
```

## Forbid self-touch

The last rule stops a path from touching itself. Stated positively: if two cells are adjacent and
carry the same number, then they must be *connected* — the path has to actually step between them,
rather than run alongside itself. That "must" is a requirement, so we reach for `require()` again —
this time on a plain atom rather than a comparison:

```python
program.section("A path may never touch itself")
program.when(
    Adjacent(cell1=C[1], direction=ANY, cell2=C[2]),
    PropagatedNumber(loc=C[1], number=Num),
    PropagatedNumber(loc=C[2], number=Num),
).require(Connected(loc1=C[1], loc2=C[2]))
```

`require()` on an atom means "this must hold." For clingo readers: it renders as a constraint with
the requirement flipped to its negation — `:- …, not connected(…)` — so it is the *un*connected
same-number adjacency that gets forbidden.

## Extract the solution

Finally, we construct a predicate to represent the final solution in a useful form. Note that
we do not include `show=False` here.

```python
class CellDirections(Predicate):
    """The solution: the two exit directions of each path cell."""
    loc: Field[Cell]
    dir1: Field[str]
    dir2: Field[str]
```

Each path cell has two exits, and we want them together in one atom. Deriving `CellDirections` from
two `PathSegment` atoms naively would give us every pair twice, once as `(e, w)` and once as
`(w, e)`, because nothing says which of the two exits comes first. So the body orders them with a
[comparison](statements.md#comparisons): `D1 < D2` keeps one of the two orderings and discards its
mirror.

```python
D1, D2 = Variable("D1"), Variable("D2")

program.section("The answer")
program.when(
    cell,
    ~Clue(loc=cell, number=ANY),
    PathSegment(loc=cell, direction=D1),
    PathSegment(loc=cell, direction=D2),
    D1 < D2,
).derive(CellDirections(loc=cell, dir1=D1, dir2=D2))
```

Note that we don't create entries for clue cells. A clue cell still has a direction leaving it — its
one path segment — so it is genuinely part of the solution; we just don't output it, because the
drawing keeps the clue's digit there rather than a line.

## Solve!

This puzzle has exactly one solution, which lets us do something the tutorial could not: assert how
many models there are.

```python
models = list(program.solve())
assert len(models) == 1, f"expected a unique solution, got {len(models)} models"
```

We can now read the first model, which contains a list of `CellDirections` instances. Each atom
has a `loc` property, which is a genuine `Cell` instance, and two strings for `dir1` and `dir2`.
A small amount of python processing later, and we have our solution printed out.

```python
GLYPHS = {
    frozenset({"n", "s"}): "│",
    frozenset({"e", "w"}): "─",
    frozenset({"n", "e"}): "└",
    frozenset({"n", "w"}): "┘",
    frozenset({"s", "e"}): "┌",
    frozenset({"s", "w"}): "┐",
}
directions = {
    (cd.loc.row, cd.loc.col): frozenset({cd.dir1, cd.dir2})
    for cd in models[0].atoms(CellDirections)
}
picture = [
    "".join(ch if ch.isdigit() else GLYPHS[directions[(r, c)]] for c, ch in enumerate(line, start=1))
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

Voila! And the picture is its own proof. Trace any digit and the line leaves it, winds through
the grid without ever crossing or touching another, and arrives at its twin; every cell is on
exactly one such line. Those are the puzzle's rules, and we can see at a glance that all of them
hold.

## The program, if you want to see it

We never needed to look at the underlying ASP while solving this puzzle, but it's available
if you're curious! You may have noticed that we emitted `section()` and `comment()` lines
along the way; those are only there to make the generated program readable, which is what
we're about to see.

```python
>>> print(program.render())
% Generated by aspalchemy ...
#const rows = 9.
#const cols = 9.

% Set up the grid
% Every cell in the grid
cell(R, C) :- R = 1..rows, C = 1..cols.
% The four directions a path may travel, and the step each one takes
direction("n", cell(-1, 0)).
direction("e", cell(0, 1)).
direction("s", cell(1, 0)).
direction("w", cell(0, -1)).
% Which directions are opposite of each other
opposite("n", "s").
opposite("s", "n").
opposite("e", "w").
opposite("w", "e").
% Two cells are adjacent when a direction leads from one to the other
adjacent(cell(R, C), cell(R + DR, C + DC), D) :- cell(R, C), direction(D, cell(DR, DC)), cell(R + DR, C + DC).

% Clues
clue(cell(2, 5), 7).
clue(cell(2, 7), 9).
clue(cell(2, 8), 4).
clue(cell(3, 1), 6).
clue(cell(3, 3), 3).
clue(cell(4, 4), 8).
clue(cell(4, 8), 5).
clue(cell(5, 2), 3).
clue(cell(5, 4), 6).
clue(cell(5, 5), 7).
clue(cell(6, 3), 8).
clue(cell(7, 1), 2).
clue(cell(8, 5), 1).
clue(cell(9, 1), 1).
clue(cell(9, 2), 2).
clue(cell(9, 7), 4).
clue(cell(9, 8), 5).
clue(cell(9, 9), 9).

% The rules
% An endpoint gets one path exit
{ path_segment(cell(R, C), D) : adjacent(cell(R, C), _, D) } = 1 :- clue(cell(R, C), _).

% All other cells get two path exits
{ path_segment(cell(R, C), D) : adjacent(cell(R, C), _, D) } = 2 :- cell(R, C), not clue(cell(R, C), _).

% If Cell A has a path segment pointing to Cell B, then Cell B has a path segment pointing to Cell A
path_segment(C_2, OppD) :- path_segment(C_1, D), adjacent(C_1, C_2, D), opposite(D, OppD).

% Two cells are connected if the path steps between them
connected(C_1, C_2) :- path_segment(C_1, D), adjacent(C_1, C_2, D).

% A cell connected to a cell carrying a number carries that number too
propagated_number(C, Num) :- clue(C, Num).
propagated_number(C_2, Num) :- propagated_number(C_1, Num), connected(C_1, C_2).

% Every cell sees exactly one number: no stray loops, no paths between different numbers
:- cell(R, C), #count{ Num : propagated_number(cell(R, C), Num) } != 1.

% A path may never touch itself
:- adjacent(C_1, C_2, _), propagated_number(C_1, Num), propagated_number(C_2, Num), not connected(C_1, C_2).

% The answer
cell_directions(cell(R, C), D1, D2) :- cell(R, C), not clue(cell(R, C), _), path_segment(cell(R, C), D1), path_segment(cell(R, C), D2), D1 < D2.

#show.
#show cell_directions/3.
```

## Where next

Every technique on this page has a home page that teaches it properly: nested fields and atom
identity in [Predicates and Data](predicates.md); rule shapes, negation and pools in
[Statements and Terms](statements.md); choices and guard idioms in
[Choices and Aggregates](choices-and-aggregates.md); and model consumption in
[Solving and Results](solving.md). We recommend reading the Guide in the navigation order.
