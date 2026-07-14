# Your First Program

On this page, we solve a map-coloring problem, teaching some basic ASP concepts
and leveraging ASPAlchemy to implement everything. This whole page is one
continuous runnable script — paste each block as you go, and the `>>>` blocks
are what you would see back. By the end you'll have written a complete ASP
program, seen the exact clingo it generated, solved it, read the answer back as
typed Python, added a limit that counts across the whole solution, watched the
solver prove that a harder version of the map has no answer at all — and then
fixed it.

## Setup

```bash
pip install aspalchemy    # or: uv add aspalchemy
```

Requires Python 3.14+; clingo, the solver, is installed automatically.

## Thinking in ASP

Most programming is *imperative*: you tell the computer what to run, in what
order. Answer Set Programming (ASP) is quite different: it's a *declarative*
language, where you declare conditions that you require to hold, and otherwise
leave the business of finding answers that satisfy those conditions to an
independent solver. ASPAlchemy uses Python, an imperative language, to generate
the ASP program, and then leverages [clingo](https://potassco.org/clingo/) as
the solver to find solutions to the stated conditions. ASPAlchemy then receives
the solutions back, and can iterate over them as desired.

A program is built from four kinds of statement: **facts** (what's true — your
input data), **rules** (what follows — if this holds, so does that), **choices**
(what the solver gets to decide), and **constraints** (what's forbidden). Hand
those to clingo and it enumerates every self-consistent world — every *answer
set* or *model* — that respects all of them. The classic name for this shape is *generate
and test*: choices generate the candidate worlds, constraints kill the bad ones,
and whatever survives is a solution.

## The problem

Color a map of six western US states — Washington, Oregon, Idaho,
California, Nevada, Utah — using three colors, so that no two bordering
states share a color. Small enough to see whole, real enough to exercise
every kind of statement ASP has.

## Declare the predicates

An ASP solution is a set of *atoms* — the atoms that, taken together, satisfy
every condition in the program, and that have a reason to be there. (That second
half matters: a solution never contains an atom the program gives it no grounds
to believe, which is why we can derive the states from the borders below and get
exactly the states, and nothing else.) An atom is a *predicate* applied to a
tuple of values, like `cell(1, 2, 3)`: `cell` is the predicate, and the three
numbers are its values. You can think of a predicate as a Python dataclass with
string and integer fields, and of an atom as one instance of that class — an
analogy ASPAlchemy takes literally, because here a predicate really *is* a
class, and an atom really is an instance of it.

Solutions consist specifically of *ground* atoms — atoms with no unspecified variables
in them. `cell(1, 2, 3)` is ground, and so, technically, is `cell(1, 2, 1 + 2)`:
the solver works the arithmetic out for you, and what lands in the solution is
`cell(1, 2, 3)` either way. But `cell(1, 2, X)` is not ground, and no solution
will ever contain it: `X` is a placeholder, and a solution has no placeholders in it.

The map-coloring program needs four predicates: three for the input and the
scaffolding, one for the answer we read back.

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

We'll use `Edge` to specify the data we're working with, specifically the facts
that we're going to take as input to the problem. `Color` is used to specify
which colors we have available for coloring the map. Both of these are inputs to
the program; we use `show=False` to specify that we don't want them to be shown
as part of the output of the program.

The `Node` predicate is an internal helper. One of our rules will automatically
derive it from the edge list that we provide, so we don't need to specify
what all our states are manually. However, it's not a particularly interesting
derived quantity, so we also suppress it in the output.

The `ColoredNode` predicate is going to describe our solution: a name and color
for each state on the map. This one will be shown by default, which means that
when solutions are returned, we'll get back a list of `ColoredNode` instances
for each solution, populated with the solution values.

Declaring predicates as classes is what buys the ORM guarantees: a misspelled
field or a missing argument is a type error before clingo ever runs. The full
story of fields, naming, and visibility lives in [Predicates and Data](predicates.md).

## Load the facts

We create an `ASPProgram` object, and start telling it what the input data is. These atoms
are the *facts* we met above, and they are included in every model — although, as discussed,
we suppress their *output*.

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

Here, we constructed `Edge` and `Color` instances for each state border and color
that we want to consider in our program, and then handed them over: `program.fact()`
takes any number of atoms.

Two things are worth noting. A more complicated map just means more borders in the
list — the rest of the program is completely independent of the amount of input data.
(We'd also probably need to add a fourth color.) And getting facts into a program is
easy, whatever format you hold them in: we built the list above by hand, but you can
happily load it from a database or a data file and feed it straight in. If you're
writing ASP by hand, putting all these facts in place quickly becomes a real burden.

## Derive new facts with rules

A rule derives new facts from existing ones. We never listed the states —
they're implied by the border list, and two rules make that explicit:

```python
N = Variable("N")

# A state is anything that appears on either side of a border
program.when(Edge(a=N, b=ANY)).derive(Node(name=N))
program.when(Edge(a=ANY, b=N)).derive(Node(name=N))
```

`N` is a *variable* — the placeholder we met when we said a solution has none left in
it. It doesn't hold anything: it marks a position the solver is free to fill, and the
solver will try every value that fits. So `when(Edge(a=N, b=ANY))` matches each border
fact in turn — `N` taking the name in the `a` field each time — and `derive(Node(name=N))`
produces a `Node` atom for whatever `N` just matched. (Variable names are capitalized;
that's clingo's rule for telling a variable from a value, and we keep it in Python.)

Two properties of variables do most of the work in ASP. First, a variable that appears
more than once in a rule must take the *same* value everywhere it appears — that is how
a rule ties things to each other, and you'll see it carry the whole meaning of the
constraint below, where one `C` in two places is what says *the same color* rather than
*a color each*. Second, `ANY` is the deliberate opposite: a position you match but don't
care about, and every `ANY` is free to be something different. We want it here because
the far end of the border tells us nothing about whether this end is a state.

Our rules say "whenever there is an Edge, anything listed in either `a` or `b` is a
`Node`." Those derived `Node` atoms join the facts in every model the solver finds.

## Choose exactly one color

Facts and rules only describe what's already determined. The *generate* step
— the space of worlds the solver explores — comes from a choice rule:

```python
C = Variable("C")

# Every state picks exactly one color
program.when(Node(name=N)).derive(
    Choice(ColoredNode(name=N, color=C), condition=Color(color=C)).exactly(1)
)
```

Read it the way Python does, left to right: `when(Node(name=N))` — *for each state
N*; `.derive(Choice(...).exactly(1))` — *make exactly one `ColoredNode` atom true
for that state*; and `condition=Color(color=C)` — *drawing the candidate values of
`C` from the colors we declared*. That last argument is the piece worth slowing down
for: the condition doesn't test anything, it *supplies the menu* — the choice ranges
over exactly the colors the program declared, however many there are. This shape is
called a [conditional literal](rules.md#conditional-literals), and it reappears
inside aggregates later. Cardinalities other than "exactly one" — at least, at most,
between — are covered in [Choices and Aggregates](choices-and-aggregates.md).

## Forbid with constraints

The *test* step. A constraint names a combination of atoms that must never
hold together, and the solver discards every world that contains it:

```python
A, B = Variable("A"), Variable("B")

# Bordering states never share a color
program.forbid(
    Edge(a=A, b=B),
    ColoredNode(name=A, color=C),
    ColoredNode(name=B, color=C)
)
```

`forbid()` takes any number of conditions that must never all hold at once. It's worth unpacking
this one in a bit of detail, to see how the variables are working. It says: in the
solution, we are not allowed to have

* an `Edge` connecting A and B,
* such that A has color C,
* and B has color C as well.

Note that the conditions are joined together as *and*: the world is thrown out only when
all three hold at once, and any one of them on its own is perfectly fine. Note too that
`A`, `B` and `C` are not particular states or colors — any value can substitute in for
them, so this single statement restricts every combination simultaneously.

And this is where the sameness rule from
[Derive new facts with rules](#derive-new-facts-with-rules) carries the whole meaning. It
is the *same* `C` in both `ColoredNode` conditions that makes this say *the same color*.
One repeated letter is the entire specification of "neighbours differ".

## See the clingo you wrote

The program is complete: facts, two rules, a choice, and a constraint. We wrote all of
it in Python and never once looked at the ASP — but it was never hidden. `render()`
prints exactly the clingo source your Python authored, whole:

```python
>>> print(program.render())
% Generated by aspalchemy ...
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

Nine borders and three colors — twelve facts of data — four statements of logic,
and the `#show` directives that `show=False` earned us. That transcript is a
doctest: CI executes it and compares the whole render, line for line, so the ASP on
this page cannot drift from the ASP the library emits.

When a program misbehaves, `render()` and its annotated sibling — which maps every
ASP line back to the Python line that wrote it — are useful tools to reach for;
see [Diagnostics and Grounding](diagnostics.md).

## Solve and read back

Now we solve. We take the first solution as a model, and then extract the `ColoredNode`
instances from its atoms. Note that `.name` and `.color` are just plain Python strings.

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

That particular coloring is illustrative: the program has several answer sets, and which
one arrives first is not something to rely on — clingo will hand you the same one today,
but the order is unspecified, and a new version of the solver may pick differently. So
rather than pin the answer, let's assert the properties any valid answer must have:

```python
states = {state for border in borders for state in border}
assignment = {atom.name: atom.color for atom in model.atoms(ColoredNode)}
assert sorted(atom.name for atom in model.atoms(ColoredNode)) == sorted(states)
assert all(assignment[a] != assignment[b] for a, b in borders)
assert set(assignment.values()) <= set(colors)
```

Every state colored exactly once, no border shares a color, no invented
colors. `solve()` returns a lazy stream of models — `first()` takes one, iteration
takes as many as you ask for — and the whole reading surface is covered in
[Solving and Results](solving.md).

## Count across the whole solution

Every constraint so far has spoken about a fixed handful of atoms at a time. Real
requirements are usually about a *set* of them — how many, how much, the
biggest — and that is what aggregates are for. Say the paint comes in limited
tins: no color may cover more than three states. We'll use a `Count` aggregate to count the atoms
matching a pattern, and compare that count against a number in a
constraint:

```python
from aspalchemy import Count

program.forbid(
    Color(color=C),
    Count(N, condition=ColoredNode(name=N, color=C)) > 3,
)
```

(Extending the already-solved `program` is safe — every solve call renders the program
and creates a new solver afresh, so the new rule simply takes effect on the next call.)

Let's unpack that forbid statement in detail. It has two clauses, so it forbids any world
where both of these hold:

* `Color(color=C)` exists as an atom,
* and `Count(...) > 3`.

Remember that any value can substitute in for `C`, and that we specified the `Color` atoms
as facts in the setup. So you can read the first clause as a "for each" over colors: the
rule instantiates once per declared color, and red, green and blue are counted separately.

Next, the `Count` aggregate itself. The comparison around it is straightforward — it is
true when the count comes out greater than three — so the interesting part is the two
arguments. The `condition` is the same `condition=` we met in the choice rule, doing the
same job: it supplies what the aggregate ranges over, which here is every `ColoredNode`
atom matching `ColoredNode(name=N, color=C)` (think of this as the "menu"
of atoms to consider in the aggregate). The `element` — the first argument, `N` — is
what we count one *of*: the aggregate tallies the distinct values that `N` takes across
those atoms. And because `C` has already been pinned to one specific color by the first
clause, what we are counting is the states painted that one color.

That pinning is the part that trips people up, and the reason it matters is that **a
variable inside an aggregate is local to it**. `N` lives only inside the count: it is the
element being tallied, and it means nothing to the rest of the rule. `C` would be local
too — except that it also appears *outside* the aggregate, in `Color(color=C)`, and a
variable used in two places must take the same value in both. That is what welds the two
halves together: `Color(color=C)`, sitting outside the aggregate, is the *for each*, and
the aggregate is the *how many*.

This is why `Color(color=C)` cannot simply be dropped. Take it away and `C` appears
exactly once, inside the aggregate — so the library refuses the rule on the spot, at the
line that built it, because a variable used exactly once is nearly always a typo
([variables and safety](rules.md#variables)).

We can solve again, and see that the tins of paint are satisfied:

```python
model = program.solve().first()
tally = {c: 0 for c in colors}
for atom in model.atoms(ColoredNode):
    tally[atom.color] += 1
assert all(count <= 3 for count in tally.values())
```

In fairness, that constraint never had to work for its living: this map is so tightly
wound that the triangle of Washington, Oregon and Idaho forces all three colors, and the
remaining states are then forced too — every valid coloring paints exactly two states in
each color, so a limit of three was never in danger. The rule is here for its *shape*,
which is what you'll reach for the moment a problem is big enough to have slack in it:
count something across the whole solution, and compare the count to a bound.

## When there's no answer

What happens when the requirements can't all be met at once? Let's copy our
program and add in another state.

```python
bigger_map = program.copy()  # an independent copy; `program` is untouched

# Arizona borders California, Nevada and Utah
az_borders = [("arizona", "california"), ("arizona", "nevada"), ("arizona", "utah")]
bigger_map.fact(*(Edge(a=a, b=b) for a, b in az_borders))
```

Three new facts, and that is the whole change: every rule we already wrote picks
Arizona up for free — it becomes a `Node` because it appears in an `Edge`, it gets a
color because it is a `Node`, and it must differ from its neighbours because the
constraint speaks about *all* borders, not the nine we started with. This is what it
means for the data to be independent of the logic.

The copy carries the paint tins too, since we added that constraint before copying —
but they aren't what bites here: three tins of three states cover nine, and we only
have seven. The map itself is the problem. Seven states laced together this way cannot
be painted with three colors at all, and the solver proves it:

```python
>>> bigger_map.solve().first()
Traceback (most recent call last):
  ...
aspalchemy.exceptions.UnsatisfiableError: first() found no model: the program is unsatisfiable. ...
```

UNSAT is not an error in your code — it is the solver's *proof* that no solution
exists, which is often exactly the answer you wanted ("can this rota even be
staffed?"). Here it is a fact about the map, not a bug: three colors are not enough
for it. Open a fourth tin, and the same map solves:

```python
bigger_map.fact(Color(color="yellow"))

model = bigger_map.solve().first()
assignment = {atom.name: atom.color for atom in model.atoms(ColoredNode)}
assert len(assignment) == 7                                        # arizona included
assert all(assignment[a] != assignment[b] for a, b in borders + az_borders)  # and valid
```

When UNSAT is *not* the answer you wanted, the debugging loop is to loosen constraints
until a model appears, then tighten back one at a time. When UNSAT is a genuine
surprise, [Diagnostics and Grounding](diagnostics.md) shows how to see what the solver
saw.

## Adapt it to your problem

Everything above transfers mechanically. To model your own problem:

- **Nouns** → `Predicate` classes, with `show=False` on everything except
  the solution shape ([Predicates and Data](predicates.md)).
- **Input data** → `fact()` calls over Python structures — files, queries,
  API responses.
- **Decisions** → `Choice`, with `condition=` supplying the menu.
- **Requirements** → `forbid()` for what must never happen, `derive()` for
  what follows ([Rules and Terms](rules.md)).
- **Limits, totals, extremes** → an aggregate (`Count`, `Sum`, `SumPlus`, `Min`, `Max`)
  compared against a bound ([Choices and Aggregates](choices-and-aggregates.md)).
- **Want every solution, not just one?** Iterate `solve()` instead of
  calling `first()` ([The model stream](solving.md#the-model-stream)).

Where next: [Walkthrough: Numberlink](numberlink.md) is the natural sequel — the
same handful of verbs you just learned, pointed at a real 9×9 puzzle, where the
rules have to reason about a grid rather than a list of borders. After that, the
Guide in the nav is ordered as a curriculum — declare data, write rules, harder
rules, solve, debug, and arithmetic — so reading it in order builds the full picture.
