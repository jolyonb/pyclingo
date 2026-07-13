# Your First Program

*Map-coloring end to end, teaching exactly the ASP needed at each step; UNSAT, optimize, adaptation checklist.*

This whole page is one continuous runnable script — paste each block into a
file (or a REPL) as you go, and by the end you'll have written, solved,
broken, and optimized a complete ASP program. The first output arrives at
[Solve and read back](#solve-and-read-back); everything before that is
setup, and the payoff is worth the stretch.

## Setup

```bash
pip install aspalchemy    # or: uv add aspalchemy
```

Requires Python 3.14+ ([why](index.md#install)); clingo, the solver, is
installed automatically.

## Thinking in ASP

Answer Set Programming inverts the usual deal: instead of writing an
algorithm that searches for a solution, you describe what a solution *looks
like*, and the solver does the searching. A program is built from four kinds
of statement: **facts** (what's true — your input data), **rules** (what
follows — if this holds, so does that), **choices** (what the solver gets to
decide), and **constraints** (what's forbidden). Hand those to clingo and it
enumerates every self-consistent world — every *answer set* — that respects
all of them. The classic name for this shape is *generate and test*: choices
generate the candidate worlds, constraints kill the bad ones, and whatever
survives is a solution.

That's the whole mental model you need for this page. The theory underneath
(stable-model semantics) is deep and interesting, and the
[Potassco guide](https://potassco.org/doc/) covers it properly — go there
for the theory, when you want it. You won't need it to ship a program.

## The problem

Color a map of six western US states — Washington, Oregon, Idaho,
California, Nevada, Utah — using three colors, so that no two bordering
states share a color. Small enough to see whole, real enough to exercise
every kind of statement ASP has.

## Declare the data

An ASP program's data is just facts — named tuples of values, called
*atoms*. In ASPAlchemy, each kind of atom is a class — a *predicate* — and
each column is a typed field:

```python
from aspalchemy import ANY, ASPProgram, Choice, Field, Predicate, Variable

class Edge(Predicate, show=False):
    """States a and b share a border."""
    a: Field[str]
    b: Field[str]

class Color(Predicate, show=False):
    """A color available to paint with."""
    color: Field[str]

class Node(Predicate, show=False):
    """A state on the map, derived from the border list."""
    name: Field[str]

class ColoredNode(Predicate):
    """The color assigned to a state — the solution we read back."""
    name: Field[str]
    color: Field[str]
```

`show=False` marks a predicate as internal: inputs and scaffolding stay
hidden, and only the solution shape — here `ColoredNode` — comes back when
we read a model. Declaring predicates as classes is what buys the ORM
guarantees: a misspelled field or a missing argument is a type error before
clingo ever runs. The full story of fields, naming, and visibility lives in
[Predicates and Data](predicates.md).

## Load the facts

The input data arrives as ordinary Python structures, and `fact()` turns
them into atoms:

```python
program = ASPProgram()

# The map: six states and their borders
borders = [
    ("washington", "oregon"), ("washington", "idaho"),
    ("oregon", "idaho"), ("oregon", "california"), ("oregon", "nevada"),
    ("idaho", "nevada"), ("idaho", "utah"),
    ("california", "nevada"), ("nevada", "utah"),
]
program.fact(*(Edge(a=a, b=b) for a, b in borders))

# Three colors to paint with
colors = ["red", "green", "blue"]
program.fact(*(Color(color=c) for c in colors))
```

This is the headline trade of writing ASP in Python: in real use `borders`
arrives from `json.load(...)` or a database query, and the program reshapes
itself around whatever the data says. The declarations above are a fixed
cost; the data grows free.

## Derive: rules

A rule derives new facts from existing ones. We never listed the states —
they're implied by the border list, and two rules make that explicit:

```python
N, C, A, B = (Variable(v) for v in "NCAB")

# A state is anything that appears on either side of a border
program.when(Edge(a=N, b=ANY)).derive(Node(name=N))
program.when(Edge(a=ANY, b=N)).derive(Node(name=N))
```

`Variable("N")` is an ASP variable — a placeholder the solver fills with
every value that fits — and `ANY` is the don't-care variable, for positions
we match but never mention. These two statements render as:

```text
node(N) :- edge(N, _).
node(N) :- edge(_, N).
```

Read `:-` aloud as "if": *node N holds if edge N-to-anything holds*. Python
reads the same statement left to right — `when(...)` is the "if" part,
`derive(...)` the conclusion. Every rule shape, and everything variables can
do, is in [Rules and Terms](rules.md).

## Choose: exactly one color

Facts and rules only describe what's already determined. The *generate* step
— the space of worlds the solver explores — comes from a choice rule:

```python
# Every state picks exactly one color
program.when(Node(name=N)).derive(
    Choice(ColoredNode(name=N, color=C), condition=Color(color=C)).exactly(1)
)
```

which renders as:

```text
{ colored_node(N, C) : color(C) } = 1 :- node(N).
```

Read it word by word, right to left: `:- node(N)` — *for each state N*;
`{ colored_node(N, C) ... } = 1` — *make exactly one `colored_node` atom
true for that state*; and `: color(C)` — *drawing the candidate values of C
from the atoms of `color`*. That last part is the `condition=` argument, and
it's the piece worth slowing down for: the condition doesn't test anything,
it *supplies the menu* — the choice ranges over exactly the colors the
program declared, however many there are. This `head : condition` shape is
called a [conditional literal](rules.md#conditional-literals), and it
reappears inside aggregates later. Cardinalities other than "exactly one" —
at least, at most, between — are covered in
[Choices and Aggregates](choices-and-aggregates.md).

## Forbid: constraints

The *test* step. A constraint names a combination of atoms that must never
hold together, and the solver discards every world that contains it:

```python
# Bordering states never share a color
program.forbid(Edge(a=A, b=B), ColoredNode(name=A, color=C), ColoredNode(name=B, color=C))
```

```text
:- edge(A, B), colored_node(A, C), colored_node(B, C).
```

A headless "if": *if A borders B and both are colored C — reject the world.*
That single statement is the entire specification of "neighbours differ".

## Solve and read back

The program is complete: facts, two rules, a choice, a constraint. Solve it
and read the answer back as typed atoms — `.name` and `.color` are plain
Python strings, no unwrapping:

```python
model = program.solve().first()
for atom in sorted(model.atoms(ColoredNode), key=lambda c: c.name):
    print(f"{atom.name} -> {atom.color}")
```

```text
california -> red
idaho -> red
nevada -> blue
oregon -> green
utah -> green
washington -> blue
```

That particular coloring is illustrative: the program has many answer sets,
and which one arrives first is deterministic for a given clingo version but
not promised across upgrades. What *is* promised is validity — so instead of
pinning the exact coloring, check the properties every answer must have:

```python
states = {state for border in borders for state in border}
assignment = {atom.name: atom.color for atom in model.atoms(ColoredNode)}
assert sorted(atom.name for atom in model.atoms(ColoredNode)) == sorted(states)
assert all(assignment[a] != assignment[b] for a, b in borders)
assert set(assignment.values()) <= set(colors)
```

Every state colored exactly once, no border shares a color, no invented
colors. (These asserts run in CI, like every Python block on this site.)
`solve()` returns a lazy stream of models — `first()` takes one, iteration
takes as many as you ask for — and the whole reading surface is covered in
[Solving and Results](solving.md).

## See the clingo you wrote

Everything above built an ASP program without showing it to you. It was
never hidden — `render()` prints exactly the clingo source your Python
authored (version-stamped header comment trimmed):

```python
rendered = program.render()
print(rendered)
```

```text
edge("washington", "oregon").
edge("washington", "idaho").
edge("oregon", "idaho").
edge("oregon", "california").
edge("oregon", "nevada").
edge("idaho", "nevada").
edge("idaho", "utah").
edge("california", "nevada").
edge("nevada", "utah").
color("red").
color("green").
color("blue").
node(N) :- edge(N, _).
node(N) :- edge(_, N).
{ colored_node(N, C) : color(C) } = 1 :- node(N).
:- edge(A, B), colored_node(A, C), colored_node(B, C).

#show.
#show colored_node/2.
```

Nine borders and three colors — twelve facts of data — four statements of
logic, and the `#show` directives
that `show=False` earned us. Every page on this site shows its generated ASP
this way — the rendered program is the receipt for every claim the Python
makes, and these lines are pinned in CI:

```python
assert "node(N) :- edge(N, _)." in rendered
assert "{ colored_node(N, C) : color(C) } = 1 :- node(N)." in rendered
assert ":- edge(A, B), colored_node(A, C), colored_node(B, C)." in rendered
assert "#show colored_node/2." in rendered
```

When a program misbehaves, `render()` and its annotated sibling — which maps
every ASP line back to the Python line that wrote it — are the first tools
to reach for; see [Diagnostics and Grounding](diagnostics.md).

## When there's no answer

What happens when the constraints can't all be satisfied? Washington, Oregon
and Idaho all border each other, so a triangle of states needs three colors
— give the program only two and no valid world exists. Because the program
is Python, building the variant is a loop body, not a second file:

```python
two_color = ASPProgram()
two_color.fact(*(Edge(a=a, b=b) for a, b in borders))
two_color.fact(*(Color(color=c) for c in ["red", "green"]))
two_color.when(Edge(a=N, b=ANY)).derive(Node(name=N))
two_color.when(Edge(a=ANY, b=N)).derive(Node(name=N))
two_color.when(Node(name=N)).derive(
    Choice(ColoredNode(name=N, color=C), condition=Color(color=C)).exactly(1)
)
two_color.forbid(Edge(a=A, b=B), ColoredNode(name=A, color=C), ColoredNode(name=B, color=C))
```

Two colors never suffice here, and the solver says so:

```python
>>> two_color.solve().first()
Traceback (most recent call last):
  ...
aspalchemy.exceptions.UnsatisfiableError: first() found no model: the program is unsatisfiable. ...
```

UNSAT is not an error in your code — it's the solver's *proof* that no
solution exists, which is often exactly the answer you wanted ("can this
rota even be staffed?"). When it's not the answer you wanted, the debugging
loop is to loosen constraints until a model appears, then tighten back one
at a time; `first()` raises `UnsatisfiableError` while iterating `solve()`
simply yields nothing, and [Solving and Results](solving.md) covers both.
When UNSAT is a genuine surprise,
[Diagnostics and Grounding](diagnostics.md) shows how to see what the
solver saw.

## Count and prefer

Two extensions turn the tutorial program into something that looks like real
work. Extending the already-solved `program` is safe — every solve renders
and grounds afresh, so additions simply take effect on the next call.

First, an aggregate: forbid any color from painting more than three states.
`Count` counts matching atoms, and comparing it to a number makes a
constraint — the tutorial's one touch of arithmetic:

```python
from aspalchemy import Count

program.forbid(Color(color=C), Count(N, ColoredNode(name=N, color=C)) > 3)

model = program.solve().first()
tally = {c: 0 for c in colors}
for atom in model.atoms(ColoredNode):
    tally[atom.color] += 1
assert all(count <= 3 for count in tally.values())
assert ":- color(C), #count{ N : colored_node(N, C) } > 3." in program.render()
```

```text
:- color(C), #count{ N : colored_node(N, C) } > 3.
```

Second, a preference: suppose red paint is expensive. `penalize()` charges
for each red state instead of forbidding them, and `optimize()` finds the
cheapest world:

```python
program.penalize(ColoredNode(name=N, color="red"), terms=[N])
```

```python
>>> best = program.optimize()
>>> best.cost  # red states in the best coloring
(2,)
```

`terms=[N]` makes each state a distinct charge — one penalty per red state,
not one penalty for "any red exists"; drop it and the cost would max out
at 1.

The optimum is provably 2 — the triangle forces a third color somewhere, and
two red states is the least this map can get away with — which is why the
transcript above can pin it: optimal *cost* is unique even when the optimal
coloring isn't. (`cost` is a tuple — one entry per priority tier, and this program
has one tier — see [Solving and Results](solving.md#optimization).) The
five aggregates live in
[Choices and Aggregates](choices-and-aggregates.md); objectives, priorities,
and everything `Optimum` carries are in
[Solving and Results](solving.md#optimization).

## Adapt it to your problem

Everything above transfers mechanically. To model your own problem:

- **Nouns** → `Predicate` classes, with `show=False` on everything except
  the solution shape ([Predicates and Data](predicates.md)).
- **Input data** → `fact()` calls over Python structures — files, queries,
  API responses.
- **Decisions** → `Choice`, with `condition=` supplying the menu.
- **Requirements** → `forbid()` for what must never happen, `derive()` for
  what follows ([Rules and Terms](rules.md)).
- **Preferences** → `penalize()` or `minimize()`, then `optimize()`.
- **Numbered slots, times, sizes** → `Field[int]` and `pool(range(1, 9))` —
  the first move for scheduling problems
  ([Pools and ranges](rules.md#pools-and-ranges)).
- **Want every solution, not just one?** Iterate `solve()` instead of
  calling `first()` ([The model stream](solving.md#the-model-stream)).

Where next: the Guide in the nav is ordered as a curriculum — declare data,
write rules, harder rules, solve, debug — so reading it in order builds the
full picture. If you already write clingo,
[Clingo to ASPAlchemy](clingo-map.md) is your front door instead. And to see
these idioms doing finished work, read
[aspuzzle](https://github.com/jolyonb/aspuzzle), a grid-puzzle framework
built entirely on aspalchemy.
