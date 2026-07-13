# Predicates and Data

*The data boundary: declaring, typed fields, naming/visibility, dynamic definition, classical negation, atom identity.*

Predicates are where your problem's data crosses into ASP and back: every fact
you write and every atom you read out of a solution is an instance of a
`Predicate` class. This page covers declaring those classes and what their
instances do; for using them in rules, see [Rules and Terms](rules.md).

## Declaring predicates

Declare a predicate as a class; each annotated field is one argument slot.
Fields are statically checked, so a misspelled field or a missing argument is
a type error before clingo ever runs — and the generated `__init__` refuses
both at runtime too, on the Python line at fault:

```python
from aspalchemy import Field, Predicate

class Person(Predicate):
    name: Field[str]
    age: Field[int]

john = Person(name="john", age=30)
mary = Person(name="mary", age=25)
```

```python
>>> john.render()
'person("john", 30)'
>>> john.age  # reads back as a plain int
30
```

This is the typed form from [the tutorial](getting-started.md), and it is the
default: annotate every field whose ground type you know. When a slot
genuinely has to hold *anything* — ints, strs, variables, expressions, pools,
other atoms — there is an untyped fallback, `PredicateField`:

```python
from aspalchemy import PredicateField

class Waypoint(Predicate):
    label: PredicateField
    order: PredicateField

stop = Waypoint(label="dock", order=1)
```

```python
>>> stop.render()
'waypoint("dock", 1)'
```

The price of the open slot is on the read side: an untyped field reads back
as a wrapped term (`stop.order` is a `Number`, not an `int`), where a typed
field reads back as plain Python. That trade is the subject of the next
section. The full declaration surface is catalogued in the
[API reference](reference.md#declaring-predicates).

## Writes and reads

Every `Field[int]`, `Field[str]`, or `Field[SomePredicate]` annotation gives
its slot a contract. Writes accept the ground type *or* rule terms
(Variables, Expressions), so the same class serves in facts and in rules;
ground writes are validated per field. Reads are plain typed Python — a
solution atom's fields come back as real ints and strs, no unwrapping:

```python
from aspalchemy import ASPProgram, Field, Predicate

class Score(Predicate):
    player: Field[str]
    points: Field[int]

program = ASPProgram()
program.fact(Score(player="ada", points=3), Score(player="ben", points=5))
model = program.solve().first()  # raises UnsatisfiableError if there is no model
total = sum(score.points for score in model.atoms(Score))  # plain ints
assert total == 8
```

This is the typed round trip at its smallest; here is
what each half of the contract looks like at the boundary. A rule term passes
straight through, a wrong-typed ground value is refused at construction:

```python
>>> from aspalchemy import Variable
>>> P, N = Variable("P"), Variable("N")
>>> Score(player=P, points=N).render()  # rule terms pass through
'score(P, N)'
>>> Score(player="ada", points="three")
Traceback (most recent call last):
  ...
TypeError: Field 'points' expects int, got str
```

One footnote on the static types: fields are typed by their *ground* schema,
so a rule atom like `Score(points=N)` transiently holds a Variable that a type
checker still calls `int` — reads of non-ground atoms are the one place the
annotations overpromise. And if you add `Field[...]` to an existing untyped
schema, every read site changes from wrapped terms to plain values (`atom.points.value`
becomes `atom.points`) — migrate the reads together with the annotation.
Reading solutions in bulk is covered in
[Solving and Results](solving.md#reading-models).

## Names, namespaces, and visibility

The ASP name defaults to the class name, snake-cased (`HasSymbol` becomes
`has_symbol`). Class keyword arguments override the name, add a namespace
prefix, and set default visibility — `show=False` is the standard idiom for
input and scaffolding predicates, so that only the solution shape reaches the
model. `in_namespace("ns")` clones a class under a namespace: the clone is
cached (repeated calls return the same class), inherits the fields and their
typing, and its instances are never equal to the original's — the namespace is
part of a predicate's identity:

```python
class HasSymbol(Predicate):
    loc: Field[int]

class Pipe(Predicate, name="pipe_seg", show=False):
    length: Field[int]

GridSymbol = HasSymbol.in_namespace("grid")
```

```python
>>> HasSymbol(loc=3).render()
'has_symbol(3)'
>>> Pipe(length=4).render()
'pipe_seg(4)'
>>> GridSymbol(loc=3).render()
'grid_has_symbol(3)'
>>> HasSymbol.in_namespace("grid") is GridSymbol  # clones are cached
True
```

Visibility can also be overridden per program, without touching the class:
`program.show(P)` and `program.hide(P)` flip one predicate's visibility for
that program, and `program.show_when(cond)` shows a predicate only where a
condition holds — its argument is a
[conditional literal](rules.md#conditional-literals). The rendered program
makes visibility explicit: aspalchemy always emits a bare `#show.` (hide
everything by default) followed by one `#show name/arity.` line per visible
predicate:

```python
viz = ASPProgram()
viz.fact(HasSymbol(loc=3), Pipe(length=4))
viz.hide(HasSymbol)  # default-shown, hidden here
viz.show(Pipe)       # default-hidden, shown here
rendered = viz.render()
assert "#show pipe_seg/1." in rendered
assert "#show has_symbol/1." not in rendered
```

One guardrail worth knowing: `show()` of a predicate the program provably
never derives is an error at render — showing states an expectation, and a
signature that cannot exist means something is misspelled.

## Bare atoms and the one-text-type design

Plain Python literals coerce automatically wherever terms are expected — an
int becomes an ASP number, a str becomes a quoted ASP string. Variables you
construct by hand, and bare atoms (the `n` in `direction(n)`) are zero-arity
predicates:

```python
from aspalchemy import Predicate, Variable

X = Variable("X")  # an ASP variable
n = Predicate.define("n", [], show=False)()  # a bare atom: n, distinct from the string "n"
```

Zero-arity is not a workaround — it is clingo's own data model, where a
symbolic constant *is* a function of arity zero. (`Predicate.define` is
covered [below](#dynamic-predicates).) The receipt, side by side:

```python
>>> Direction = Predicate.define("direction", ["d"], show=False)
>>> Direction(d=n).render()
'direction(n)'
>>> Direction(d="n").render()
'direction("n")'
```

There is deliberately no Symbol type: a Python `str` always means a quoted ASP
string, and a symbolic constant is always a bare atom you declared. One text
type, no ambiguity — you never have to guess whether `"n"` will render quoted.
This is one of the [design stances](unsupported.md) the library holds
throughout; if you drive the clingo API directly and need to cross between
typed atoms and `clingo.Symbol` objects, see
[symbol interop](escape-hatches.md#clingo-symbol-interop).

## Dynamic predicates

When the schema is only known at runtime — generated programs, schemas read
from configuration — build the same thing dynamically:

```python
>>> Edge = Predicate.define("edge", ["a", "b"])
>>> Edge(a=1, b=2).render()
'edge(1, 2)'
```

This is not a second-class citizen: `define()` and the class statement share a
single creation path, so the resulting classes behave identically —
`namespace=` and `show=` are keyword arguments, and passing a dict such as
`Predicate.define("clue", {"loc": str, "value": int})` gives runtime-typed
slots with the same write validation and plain-Python reads as `Field[...]`.
The one caveat: a `define()`-built class cannot be found by name on import, so
its atoms don't pickle — the refusal is a teaching error, and the remedy is to
transport such atoms as rendered text. `copy.deepcopy` still works fine:

```python
>>> import copy
>>> import pickle
>>> atom = Edge(a=1, b=2)
>>> pickle.dumps(atom)
Traceback (most recent call last):
  ...
TypeError: edge atoms do not pickle: the class was built at runtime ...
>>> copy.deepcopy(atom) is atom  # atoms are immutable; deepcopy is free
True
```

## Classical negation

Unary minus on an atom flips its sign: `-Safe(node="b")` renders as
`-safe("b")`. The sign is part of the atom, exactly as in clingo's own symbol
model — a negated atom is *not* a different predicate, and not a wrapper: it
is the same class, and `atoms()` returns both signs together, with `.negated`
telling them apart:

```python
from aspalchemy import UnsatisfiableError

class Safe(Predicate):
    node: Field[str]

signs = ASPProgram()
signs.fact(Safe(node="a"), -Safe(node="b"))
rendered = signs.render()
assert '-safe("b").' in rendered
assert "#show safe/1." in rendered and "#show -safe/1." in rendered

model = signs.solve().first()
assert sorted(a.render() for a in model.atoms(Safe)) == ['-safe("b")', 'safe("a")']
negated = next(a for a in model.atoms(Safe) if a.negated)
assert negated.node == "b"
```

Because the sign is part of the atom, `safe("x")` and `-safe("x")` are a
genuine contradiction: any program that derives both has no answer sets.

```python
clash = ASPProgram()
clash.fact(Safe(node="x"), -Safe(node="x"))
```

```python
>>> clash.solve().first()
Traceback (most recent call last):
  ...
aspalchemy.exceptions.UnsatisfiableError: first() found no model: the program is unsatisfiable. ...
```

(This is different from default negation `~Safe(...)` — "not known to be safe"
— which lives in [Rules and Terms](rules.md#default-negation).)

Minus also works on the *class*: `-Safe` builds a `NegatedSignature`, a
declaration rather than an atom. You only need it when a `raw_asp()` block
derives negated atoms that aspalchemy can't see — declaring `-Safe` in the
block's `predicates=` list gets the `#show -safe/1.` directive emitted. See
[the predicates= seatbelt](escape-hatches.md#the-predicates-seatbelt).

## Atoms as values

Identity has two layers here, and both are guarantees you can lean on. Values
(numbers, strings, variables) *intern*: equal live values are the same
object, and they hash by identity. That is what makes sets and dicts
containing them work at all, because `==` on a Value doesn't answer a question
— it builds a Comparison term for use in rules. Atoms are the deliberate
exception: predicates round-trip through the solver as data, so `==` on a
Predicate instance is real equality (same class, same sign, identically
rendered arguments), and atoms work directly as set members and dict keys:

```python
from aspalchemy import String

assert String("hello") is String("hello")  # equal live values intern to one object

class Cell(Predicate):
    row: Field[int]
    col: Field[int]

assert Cell(row=1, col=2) == Cell(row=1, col=2)          # atoms compare as data
assert len({Cell(row=1, col=2), Cell(row=1, col=2)}) == 1  # sets and dict keys work
```

Atoms are immutable, so "editing" one means building a changed copy — and
there is exactly one right tool. `copy.replace(atom, field=...)` preserves the
classical-negation sign. `dataclasses.replace()` looks equivalent, cannot be
hooked, and silently drops the sign — never use it on atoms:

```python
import dataclasses

flagged = -Cell(row=1, col=2)
moved = copy.replace(flagged, col=3)
assert moved.render() == "-cell(1, 3)"  # the sign survives

dropped = dataclasses.replace(flagged, col=3)
assert dropped.render() == "cell(1, 3)"  # sign silently gone — never do this
```
