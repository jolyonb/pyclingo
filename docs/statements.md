# Statements and Terms

If predicates are your data, statements are how you compute with it: what to derive, what to rule out, what
must hold. This page is the vocabulary for writing them, and it comes in two halves — the handful of
*verbs* that put statements into a program, and the *terms* those verbs accept. We'll walk the verbs
first, then each kind of term in turn. (For the predicates these statements
operate on, see [Predicates and Data](predicates.md).)

## The verbs

A program is built from three kinds of statement — **facts**, **rules**, and **constraints** — and the
one distinction to hold onto is what each does to the answer set. **Facts and rules construct it**: a fact
puts an atom in unconditionally, a rule puts one in whenever its conditions hold. A **constraint constructs
nothing** — it only takes answer sets away, ruling out any in which a forbidden situation occurs. Nothing
but a fact or a rule ever makes an atom true.

Each kind is written with its own verb: `fact()` asserts a fact, `when(...).derive(...)` builds a rule,
and a constraint is a `forbid()` or a `require()`. (Letting the solver *choose* what to construct, and
ranking the solutions it finds, are separate verbs on their own pages —
[Choices and Aggregates](choices-and-aggregates.md) and [Solving and Results](solving.md#optimization).)

If you've written raw clingo, two things may feel unfamiliar. First, the verbs don't line up one-to-one
with those three kinds: a rule isn't a single call but a `when()` — the conditions — closed with
`.derive()` — what they produce, and a constraint is a deliberate `forbid()` or `require()` rather than a
bare `:-` line. Second, there are more verbs than kinds: constraints alone come as `forbid()`, `require()`,
and their `when()` forms, and choices and preferences bring their own later. The reason for these new verbs
is simply that we want to make the code readable — when you read a rule constructed in Python, its intent
should be obvious. Under the hood, everything is converted appropriately and renders in standard clingo notation.

We'll build one small program to demonstrate each verb — a guest list:

```python
from aspalchemy import ANY, ASPProgram, Field, Predicate, Variable

class Guest(Predicate):
    name: Field[str]
    age: Field[int]

class Adult(Predicate):
    name: Field[str]

X, Y = Variable("X"), Variable("Y")
party = ASPProgram()
```

Facts, rules, and constraints all need to be attached to a program: we've called ours `party`.

### Facts

`fact(*atoms)` asserts atoms unconditionally, and it takes any number of them — as long as they're
**ground** (no variables). Here are our first two guests:

```python
party.fact(Guest(name="alice", age=30), Guest(name="bob", age=17))
```

That makes `fact()` the natural landing point for your Python data: unpack a generator over your input
rows and the facts write themselves.

```python
guests = [("carol", 41), ("dan", 12)]
party.fact(*(Guest(name=n, age=a) for n, a in guests))
```

An atom with a variable in it isn't data though, so `fact()` refuses it:

```python
>>> party.fact(Guest(name=X, age=30))
Traceback (most recent call last):
  ...
ValueError: fact() requires grounded predicates, but guest(X, 30) contains variable(s) X. Use when(*conditions).derive(...) to derive predicates.
```

### Rules: when().derive()

Rules derive an atom when a set of conditions holds. Sometimes you'll see the derived atom called a "head" and
the conditions called a "body", named after the ASP code `head :- body.` that describes a rule.

ASPAlchemy splits rules into their two separate components. We start by stating `when(*conditions)`, which
takes one or more conditions, then close the rule with `.derive(atom)` — the atom to derive when they
hold. Let's see it in action, where we wish to specify that guests 18 years or older are adults.

```python
party.when(Guest(name=X, age=Y), Y >= 18).derive(Adult(name=X))
```

Our `when()` holds two conditions: a `Guest` atom — matched for every guest that exists — and the comparison `Y >= 18`.
Because `alice` is 30 (and `carol` 41), the rule **derives** `adult("alice")` and `adult("carol")` —
atoms the facts never contained. `bob` and `dan` are under 18, so no `adult` for them. Solving the program
shows the rule's handiwork:

```python
>>> sorted(a.render() for a in party.solve().first().atoms(Adult))
['adult("alice")', 'adult("carol")']
```

The two halves `when` and `derive` are really one statement, so a `when()` you never close is an
error at render, and the report points back to the line where you opened it (every statement remembers
the line that authored it — see [source locations](diagnostics.md#source-locations)). Let's take a look:

```python
>>> Minor = Predicate.define("minor", ["name"], show=False)
>>> pending = party.when(Guest(name=X, age=Y), Y < 18)
>>> party.render()
Traceback (most recent call last):
  ...
ValueError: Segment 'Rules' has incomplete when() statements: when(guest(X, Y), Y < 18) opened at ...
>>> pending.derive(Minor(name=X))  # closed; the program renders again
```

`derive()` is one way to close a `when()`; another option lets you create a **constraint**, as we'll see below.
Two more closers, `choose` and `penalize`, belong to [choices](choices-and-aggregates.md#choice-rules) and [optimization](solving.md#optimization). Exactly one
closer finishes each `when()`, and closing it twice is an error, the same as never closing it.

### Constraints: forbid() and require()

Now the third kind of statement — the one that constructs nothing. `forbid(*conditions)` bans a
combination outright: no answer set may satisfy all its conditions at once. It renders as `:- conditions.`,
clingo's own way of writing "this must never happen".

`require(target)` says it the other way round: you name the thing that must *hold*, and the library
forbids its opposite. Requiring an atom forbids its default negation — `require(p)` renders `:- not p` —
and requiring a comparison flips it to the inverse. A bare `require(target)` is a whole constraint on its
own — though that form is fairly rare.

Closing a `when()` with `.require()` is a different statement: `when(*conditions).require(target)` asks that
`target` hold **whenever** the conditions do, rendering `:- conditions, <target's opposite>`. And
crucially, those conditions *bind* the variables the target uses: `Y` draws its
values from the `guest` condition rather than appearing from nowhere.

The final form of constraint that you can use is `when(*conditions).forbid(*targets)`, which is just an
alias for `forbid(*conditions, *targets)`. However, being able to write it as `when().forbid()` gives you
an option to organize your thoughts around "what is the condition" and "what am I actually forbidding".

Let's see a couple of these in action.

```python
party.when(Guest(name=ANY, age=Y)).forbid(Y < 0)     # ban: a negative age
party.when(Guest(name=ANY, age=Y)).require(Y < 150)  # every guest: age under 150
```

Here is the whole program now — facts, rules, and constraints together:

```python
>>> print(party.render())
% Generated by aspalchemy ...
guest("alice", 30).
guest("bob", 17).
guest("carol", 41).
guest("dan", 12).
adult(X) :- guest(X, Y), Y >= 18.
minor(X) :- guest(X, Y), Y < 18.
:- guest(_, Y), Y < 0.
:- guest(_, Y), Y >= 150.

#show.
#show adult/1.
#show guest/2.
```

None of our guests break those constraints, so the program is satisfiable. Solving it returns a single
answer set — the guests, plus the two adults the rule derived (the minors are derived too, but `show=False`
keeps them out of the report):

```python
>>> model = party.solve().first()
>>> sorted(atom.render() for atom in model.atoms())
['adult("alice")', 'adult("carol")', 'guest("alice", 30)', 'guest("bob", 17)', 'guest("carol", 41)', 'guest("dan", 12)']
```

## Variable binding

That's all three statements — fact, rule, and constraint. Everything from here on is the *terms* those verbs accept —
but before the catalogue, one idea sits under all of them, quietly at work in every rule so far:
**binding**. It's the answer to a question the examples kept begging — how does the `X` in
`Guest(name=X, age=Y)` know which guests to stand for?

The `X` and `Y` you've been reading are **variables**: placeholders that hold no value as you write them,
and that solving fills in. clingo does this by **grounding** — before it searches for answer sets it
instantiates each rule, trying every substitution of concrete terms for the variables that makes the body
true, and turning one rule-with-variables into many ground copies. The adult rule,
`adult(X) :- guest(X, Y), Y >= 18.`, is never solved as written; it's ground against the four `guest`
facts, one candidate copy per matching guest.

Where do a variable's values come from? From the **positive body atoms** it appears in — the plain,
un-negated predicates in the `when()`. In that rule `guest(X, Y)` is the positive atom, and it's what
*binds* `X` and `Y`: each `guest` fact is one substitution, so `X` ranges over the four names and `Y` over
their ages. Everything else only *reads* a value some positive atom already supplied. `Y >= 18` invents no
ages — it filters the ones `guest(X, Y)` handed it; `adult(X)` invents no names — it carries
the `X` that the body bound. That is the whole reason the rule derives `adult("alice")` and `adult("carol")`
and nothing else: those are the substitutions where a bound `Y` also cleared the comparison.

The flip side is the rule you *can't* ground. A variable that shows up only in places that read — in the
head, under a `not`, or in a comparison — with no positive atom to bind it is **unsafe**: clingo has no
set of values to range it over. So the discipline is a one-liner: every variable must appear in at least
one positive body atom. ASPAlchemy enforces it and flags a violation at the line that built the rule — the
[next section](#variables) shows it happening. (One term does both: an equality is clingo's *assignment*
and binds — `X == Y + 1`, or a domain `X.in_(...)` — so it counts as positive too; see
[Comparisons](#comparisons).)

## Variables

With binding in hand, the mechanics of the variable itself are quick.

`Variable("X")` is an ASP variable — during solving it ranges over every ground term: numbers, strings,
and whole atoms alike. Names start with an uppercase letter. Two shorthands cover the common cases. The
module-level `V` (a ready-made `Vars` instance) mints variables by attribute access, so `V.Room` is
`Variable("Room")` with no declaration first; and `ANY` is the anonymous variable `_` for a don't-care
position, as in the `Edge(a=N, b=ANY)` rules of
[the tutorial](getting-started.md#derive-new-facts-with-rules). ASPAlchemy is slightly stricter on
variable names than clingo: all anonymous variables must be simply `ANY`; `_X` is disallowed.

```python
>>> from aspalchemy import V
>>> V.Room.render()
'Room'
>>> ANY.render()
'_'
```

A variable that appears exactly once in a rule is almost always a typo, so ASPAlchemy rejects it.
The fix is either the variable you actually meant, or `ANY` to say the don't-care out loud.
(Note that this is stricter than clingo, which will accept a singleton, but it can lead to
unexpected results, see [deliberate strictnesses](unsupported.md#deliberate-strictness).)

```python
Reading = Predicate.define("reading", ["sensor", "value"], show=False)

prog = ASPProgram()
```

```python
>>> prog.forbid(Reading(sensor=X, value=Y), X > 0)  # Y used exactly once
Traceback (most recent call last):
  ...
ValueError: Singleton variable(s) Y in rule: :- reading(X, Y), X > 0.
A variable used exactly once is usually a typo; use ANY for an intentional don't-care.
```

Unsafe variables get the same treatment — a variable that appears in the derived atom or a negative condition
but that no positive condition *binds* — flagged at the line that built the rule. Here `X` and `Y` sit
only under a `not`, where [nothing binds them](#variable-binding):

```python
>>> prog.forbid(~Reading(sensor=X, value=Y))  # X, Y appear only under `not`
Traceback (most recent call last):
  ...
ValueError: Unsafe variable(s) X, Y in rule: :- not reading(X, Y).
Every variable must be bound by a positive body literal (or an equality with something bound).
```

## Comparisons

Variables become conditions once you compare them. The Python comparison operators — `==`, `!=`, `<`,
`<=`, `>`, `>=` — applied to variables, numbers, expressions, or aggregates build **Comparison terms**,
and a comparison joins the conditions like any other; the `Y >= 18` back in the first rule was
one. Arithmetic composes underneath, so `X + 1 < Y * 2` is a comparison over expressions (the operator
table and the clingo-vs-Python fine print are in [Arithmetic](math.md)), and the right-hand side can even
be a whole atom: `X == Cell(row=1, col=2)` compares against a nested term.

There's a catch that falls out of `==` building a term: a comparison has no truth value. So `if X == Y:`
is almost always a bug, and ASPAlchemy makes it a *loud* one rather than letting you take a silently wrong
branch. Chained comparisons like `X < Y < Z` hit the same wall — Python evaluates them as
`(X < Y) and (Y < Z)`, which needs a truth value in the middle — so pass each one separately:
`when(X < Y, Y < Z)`. (Atoms are the exception: they're ordinary data, so `==` between two atoms is plain
Python equality — see [atom identity](predicates.md#predicate-instances-as-python-values).)

```python
>>> comparison = X < Y  # a term, not a bool
>>> comparison.render()
'X < Y'
```

```python
>>> if X == Y:
...     pass
Traceback (most recent call last):
  ...
TypeError: A Comparison (X = Y) has no boolean value: comparison operators on aspalchemy terms build ASP terms rather than evaluating them. ...
```

Equality is clingo's binding assignment: `X == Y + 1` renders as `X = Y + 1`, and — as in clingo — that
equality *binds* `X`, so it counts as a positive condition for the [safety check](#variable-binding). It's
the one comparison *operator* that binds — `<`, `>`, `!=` and the rest only filter values something else
supplied.

```python
>>> (X == (Y + 1)).render()
'X = Y + 1'
```

## Default negation

Some conditions are about what *isn't* there. `~Booked(room=R)` reads "unless the room is known to be
booked" — that's *default negation*, or negation as failure: the condition holds when the atom is *not
derivable*, which is ASP's way of saying "absent from this world" rather than "provably false." It's the
workhorse behind rules like "a room with no booking is free":

```python
Room = Predicate.define("room", ["r"], show=False)
Booked = Predicate.define("booked", ["room"], show=False)
Free = Predicate.define("free", ["room"])
R = Variable("R")

hotel = ASPProgram()
hotel.fact(Room(r=1), Room(r=2), Booked(room=2))
hotel.when(Room(r=R), ~Booked(room=R)).derive(Free(room=R))
```

```python
>>> print(hotel.render())
% Generated by aspalchemy ...
room(1).
room(2).
booked(2).
free(R) :- room(R), not booked(R).

#show.
#show free/1.

>>> model = hotel.solve().first()
>>> [atom.render() for atom in model.atoms(Free)]
['free(1)']
```

Room 1 has no `booked` fact, so `free(1)` is derived; room 2's booking blocks it. Notice which condition
carries the weight for [binding](#variable-binding): `R` is bound by the positive `Room(r=R)`, and the
negated `~Booked(room=R)` only *reads* it — a `not` condition can never bind a variable, which is why a
rule negating the only occurrence of a variable is unsafe. One practical note: that
`Booked(room=2)` fact is load-bearing. If a default-negated predicate is never derived *anywhere* — no
fact, no rule — gringo flags it ("atom does not occur in any rule head"). Raw clingo shrugs and
grounds anyway (the negation trivially holds), but a never-derivable atom in a condition is usually a
misspelled predicate name, so ASPAlchemy [makes that message loud](diagnostics.md#clingos-messages) at
solve time by default.

`~` and the named form `Not()` are the same operation — use whichever reads better. (The *other* negation,
the classical minus sign that's part of the atom itself, lives in
[Predicates and Data](predicates.md#classical-and-default-negation).)

The fine print, for when you nest negations or negate a comparison:

- On atoms, a **double negation is preserved**: `not not p` is *not* equivalent to `p` under stable-model
  semantics, and a triple collapses to a single. (Contrast arithmetic, where `-` and `Compl` really are
  involutions, so a doubled one collapses — see
  [doubled unary operators](math.md#doubled-unary-operators).)
- On a **plain comparison**, `~`/`Not()` return the *complement* rather than wrapping: `Not(X != 5)` is
  the binding equality `X = 5`. That's gringo's own normalization, done at construction where you can see
  it.
- A comparison **carrying an aggregate** keeps the `not` wrapper — a negated aggregate literal can't be
  complement-flipped.

```python
>>> from aspalchemy import Count, Not
>>> b = Booked(room=R)
>>> Not(Not(b)).render()  # double survives
'not not booked(R)'
>>> Not(Not(Not(b))).render()  # triple collapses
'not booked(R)'
>>> Not(X != 5).render()  # complement, not wrapper
'X = 5'
>>> Not(Count(X, condition=Booked(room=X)) > 2).render()  # aggregates keep "not"
'not #count{ X : booked(X) } > 2'
```

## Conditional literals

A conditional literal is clingo's `p(X) : q(X)`. In a rule it means "for **every** `X` where `q(X)`
holds, `p(X)` holds too." A picture that might help: `p(X)` is a *key* and `q(X)` a *lock*,
and the literal holds when every lock has a matching key. Keys without locks are fine; a lock with no key
fails.

```python
from aspalchemy import ConditionalLiteral

Cell = Predicate.define("cell", ["id"], show=False)
Covered = Predicate.define("covered", ["id"], show=False)
AllCovered = Predicate.define("all_covered", [])

board = ASPProgram()
board.when(ConditionalLiteral(Covered(id=X), Cell(id=X))).derive(AllCovered())
```

```python
>>> print(board.render())
% Generated by aspalchemy ...
all_covered :- covered(X) : cell(X).

#show.
#show all_covered/0.
```

You build a `ConditionalLiteral` by hand in exactly two places: rule bodies (as above) and `show_when()`
([conditional visibility](predicates.md#predicate-visibility)). Conditional structure shows up elsewhere
too — in the elements of [choices and aggregates](choices-and-aggregates.md) — but those build their own
elements through `add()`, so you never hand them one.

## Pools and ranges

A pool is clingo's several-values-at-once notation: `RangePool(1, 5)` renders as `1..5`, and
`ExplicitPool([1, 3, 5])` as `(1; 3; 5)`. Usually you let the `pool()` helper pick — it takes plain Python
ranges, lists, and tuples, turning a step-1 `range` into a `RangePool` and everything else into an
`ExplicitPool`:

```python
>>> from aspalchemy import pool
>>> pool(range(1, 6)).render()
'1..5'
>>> pool([1, 3, 5]).render()
'(1; 3; 5)'
>>> pool(["a", "b"]).render()
'("a"; "b")'
>>> pool(range(1, 10, 2)).render()
'(1; 3; 5; 7; 9)'
```

Pools show up in exactly two positions. As a **predicate argument**, one atom expands to many — a whole
row of the board in a single `fact()`:

```python
Slot = Predicate.define("slot", ["n"], show=False)

grid = ASPProgram()
grid.fact(Slot(n=pool(range(1, 4))))
```

```python
>>> print(grid.render())
% Generated by aspalchemy ...
slot(1..3).

#show.
```

And on the right of a **comparison**, where `X.in_(...)` is the idiomatic way to spell a domain
restriction:

```python
>>> X.in_(range(1, 6)).render()
'X = 1..5'
>>> X.in_([2, 4, 8]).render()
'X = (2; 4; 8)'
```

Note that this usage counts as binding the variable `X`.

Those two are the only legal positions. A bare pool sitting alone as a rule element is a clingo syntax
error, so ASPAlchemy refuses it at construction — along with the subtler shapes (a negated pool
comparison, a pool inside `require()`) whose clingo reading is never what the code seems to say: see
[better errors, not restrictions](unsupported.md#better-errors-not-restrictions).

## Constants and extremes

`define_constant(name, value)` registers a clingo `#const` and hands back a `DefinedConstant` you use in
rules — one named number, string, or ground atom threaded through the program and defined in exactly one place:

```python
config = ASPProgram()
max_size = config.define_constant("max_size", 10)
Size = Predicate.define("size", ["n"], show=False)
N = Variable("N")

config.when(Size(n=N)).require(N <= max_size)
```

```python
>>> print(config.render())
% Generated by aspalchemy ...
#const max_size = 10.
:- size(N), N > max_size.

#show.
```

A `str` value renders as a quoted ASP string — `"n"` is never the bare symbol `n`. For a *symbolic*
constant, pass a ground atom instead: `define_constant("dir", North())` with
`North = Predicate.define("n", [])` renders `#const dir = n.`

Two extremes round out the vocabulary:
`SUP` and `INF` render as clingo's `#sup` and `#inf`, the greatest and least terms of the ordering. Their
everyday use is the empty-set answer — `Min` over nothing is `#sup` (and `Max` is `#inf`) — so comparing
against `SUP` is really asking "was the set empty?"

```python
>>> from aspalchemy import INF, SUP
>>> SUP.render()
'#sup'
>>> INF.render()
'#inf'
```
