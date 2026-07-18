# Predicates

Predicates are the basic building block of ASP programs, and they lie at the heart of the typing
guarantees that ASPAlchemy provides. This page walks from
declaring predicates and giving them data, through naming and hiding them in the ASP output, to the finer
points — symbolic constants, negation, declaration fine print, and atoms as first-class Python
values. For using predicates in rules, see [Statements and Terms](statements.md).

## Declaring predicates

In ASPAlchemy, a predicate is a Python class — a subclass of `Predicate`, a frozen dataclass under the
hood — and an **atom** is an instance of one. The mental model to hold:

> **class is to instance as predicate is to atom**

The predicate is the schema; an atom is one filled-in instance of it, and the unit of data that crosses
into ASP and back — every fact you assert and everything you read out of a solution is an atom.

In ASP a predicate holds a tuple of values, which we model as fields on the class — going beyond what ASP
requires by giving each field both a name and a data type. Here is a predicate and a couple of atoms:

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
>>> mary.age
25
>>> mary.name
'mary'
```

This should look almost exactly like a dataclass to those familiar with Python. Note that the order
of the arguments corresponds to the order in which the values are rendered in the tuple. The one difference
is the use of `Field[...]` in the parameter annotations: this is where we hide all the typing magic.
The fields defined above are literal strings and integers, and you can set them and read them off
as such. The field names provide a basic spell check: if you mistype a field name, Python will raise
an exception when you attempt to run that line.

The parameter annotations accept two more types. The first is another Predicate subclass — a field can
hold a whole atom, which then acts as a *function term* rather than standing alone as a top-level atom:

```python
class Grade(Predicate):
    person: Field[Person]
    grade: Field[int]

grade_john = Grade(person=Person(name="john", age=30), grade=100)
```

```python
>>> grade_john.render()
'grade(person("john", 30), 100)'
```

Note that this is written `Field[OtherPredicate]` — every annotation on a `Predicate` subclass has to be
wrapped in `Field[...]`. The remaining option is for a field whose type is unknown or polymorphic: write
`Field[PredicateArg]`, and it will accept an int, a str, or any predicate.

```python
from aspalchemy import PredicateArg

class Order(Predicate):
    item: Field[PredicateArg]
    number: Field[int]

order1 = Order(item="box", number=1)
order2 = Order(item=23, number=2)
```

The unknown type costs you static typing and write-time validation, though the field still reads back
as a plain Python int, string, or atom.

Any other type inside `Field[...]` is refused at class creation. And because these annotations are
ordinary types, mypy and pyright understand them — you get real static checking on the values you write
to a field and read back from it.

So why the `Field[...]` wrapper at all? Everything above has been a *ground* predicate — every argument a
concrete value. But ASP also lets you build predicates out of variables, defined constants, and
expressions, and a field has to hold those too. A field is typed by its *ground* schema, yet `Field` lets
it transiently carry a variable or expression that a type checker still treats as an `int`. So the
annotations can overpromise when you read a non-ground atom — but by the time you reach a solution,
everything is ground and the promises hold.

```python
from aspalchemy import Variable

X, A = Variable("X"), Variable("A")

person = Person(name=X, age=A+1)
```

```python
>>> person.render()
'person(X, A + 1)'
>>> person.name
Variable('X')
```

That read is *non-ground*, so the term comes back on its own. A ground field is the other way around:
attribute access hands you the plain Python value — `mary.age` is the `int` `25`. Occasionally you want a
ground field back as an ASP *term* instead, to build an expression out of an atom's fields, and there
`mary.age` works against you twice: it does Python arithmetic rather than ASP, and a type checker narrows
the result to `int` when a term is what you need. The subscript form `atom["field"]` is the escape hatch —
it reads the field as a term, typed loosely, so arithmetic on it builds an `Expression` object:

```python
>>> mary.age + 5                 # attribute access does Python arithmetic
30
>>> (mary["age"] + 5).render()   # subscript reads a term, so this builds an ASP expression
'25 + 5'
```

When you try to write to a field, ASPAlchemy checks that the value is the right type — writing a variable
or expression is exempt, since rule terms pass straight through.

```python
>>> Person(name=5, age=2)
Traceback (most recent call last):
  ...
TypeError: Field 'name' expects str, got int
```

This also applies when solutions are read out of a model: the data types in the solution are checked
against the types you've defined.

## Dynamic predicates

Subclassing `Predicate` is all well and good when you know the structure in advance, but what about when
the fields are only known at runtime? To help out here, we have a dynamic predicate creation helper.

```python
>>> Edge = Predicate.define("edge", ["a", "b"])
>>> Edge(a=1, b=2).render()
'edge(1, 2)'
```

The first argument is the predicate's name as it will render in ASP (it must start with a lowercase
letter); the second is the list of field names to create. Fields made this way are `Field[PredicateArg]`.
If you want to be more precise, pass a dict mapping each name to `int`, `str`, or a predicate class —
`{"a": str, "b": int}` — where a value of `None` leaves that field polymorphic.

Predicates constructed in this manner are almost entirely equivalent to statically-defined predicates. You can
even construct inheritance chains of predicates dynamically:

```python
>>> ColoredEdge = Edge.define("colored_edge", ["color"])
>>> ColoredEdge(a=1, b=2, color="red").render()
'colored_edge(1, 2, "red")'
```

The cost is that you lose static type analysis — mypy and pyright have no idea what fields a dynamically
built class has. Everything at runtime is unchanged, though: writes are still validated, and reads still
come back as plain ints and strs. One further caveat: because a dynamically-defined class can't be found
by name on import, its atoms can't be pickled.

## Names and namespaces

However you declared it — as a class or via `define()` — a predicate needs a name to render under in ASP,
and there's a small mismatch to bridge: Python classes are conventionally CamelCase, but ASP wants a
predicate name to start with a lowercase letter.
So a class-syntax predicate takes its ASP name by snake-casing its class name:

```python
class HasSymbol(Predicate):
    loc: Field[int]
```

```python
>>> HasSymbol(loc=3).render()
'has_symbol(3)'
```

If the snake-cased name isn't what you want, override it with the `name=` class keyword:

```python
class Node(Predicate, name="vertex"):
    id: Field[int]
```

```python
>>> Node(id=1).render()
'vertex(1)'
```

(Dynamically-declared predicates skip the snake-casing: the name you pass to `define()` is used verbatim,
as both the ASP name and the class name.)

Now suppose you're writing a reusable module that declares its own predicates. There's a real chance one
of your names collides with a predicate the caller already uses for something unrelated. To keep yours
distinct, a predicate can be *namespaced*. `in_namespace("ns")` clones a predicate class under a
namespace: the clone renders with the namespace as a prefix, while its Python class name stays the same.

```python
class Pipe(Predicate):
    length: Field[int]

GridPipe = Pipe.in_namespace("grid")
```

```python
>>> Pipe(length=4).render()
'pipe(4)'
>>> GridPipe(length=4).render()
'grid_pipe(4)'
>>> Pipe.in_namespace("grid") is GridPipe   # asking twice returns the same clone
True
```

The clone is cached — asking for the same namespace again hands back the very same class — because the
namespace is part of the predicate's identity. `Pipe` and `GridPipe` are genuinely different predicates,
and their atoms never compare equal.

## Predicate visibility

A name settles how a predicate renders; visibility settles whether it renders at all. By default, every
atom your program derives appears in its solutions. Often you don't want all of them —
input facts and scratch predicates are scaffolding, and you only care about the answer. A predicate's
`show` setting controls this: `show=True` (the default) includes the predicate in the output, and
`show=False` hides it. It's a property of the class, not of any single instance:

```python
from aspalchemy import ASPProgram

class Scratch(Predicate, show=False):
    val: Field[int]
```

You can also override visibility per program, without touching the class — useful when a predicate is
output in one program and scaffolding in another. `program.show(P)` and `program.hide(P)` flip a class's
default for that program, and `program.show_when(cond)` shows a predicate only where a condition holds
(its argument is a [conditional literal](statements.md#conditional-literals)).

The rendered program makes visibility explicit: ASPAlchemy emits a bare `#show.` — which tells clingo to
hide everything by default — followed by one `#show name/arity.` line for each predicate that should be
visible:

```python
class Guess(Predicate):          # shown by default
    val: Field[int]

viz = ASPProgram()
viz.fact(Guess(val=1), Scratch(val=2))
viz.hide(Guess)     # shown by default, hidden here
viz.show(Scratch)   # hidden by default, shown here
```

```python
>>> print(viz.render())
% Generated by aspalchemy ...
guess(1).
scratch(2).

#show.
#show scratch/1.
```

The facts are always in the rendered program — visibility only governs what clingo reports back. One
guardrail worth knowing: calling `show()` on a predicate the program can never derive is an error at
render. Showing states an expectation, and a signature that can't exist usually means something is
misspelled.

## Bare predicates

Everything so far has been about declaring predicates and controlling how they appear; the rest of the
page turns to the data model itself, and it opens with a small surprise. Let's look at how a string value
in a predicate renders in ASP.

```python
class Name(Predicate):
    name: Field[PredicateArg]

bob = Name(name="bob")
```

```python
>>> bob.render()
'name("bob")'
```

That's just the string `"bob"` sitting in the atom's one argument slot. If you've worked with raw ASP,
though, you probably expected `name(bob)` instead — and those are two structurally different things. Here
`"bob"` is a string; in the raw-ASP idiom, `bob` is a *zero-arity predicate* (a name with no arguments).
To render without the quotation marks, define `bob` as exactly that:

```python
class Bob(Predicate):
    pass

bob2 = Name(name=Bob())
```

```python
>>> bob2.render()
'name(bob)'
```

This works because `Name`'s field is a `Field[PredicateArg]`, so it accepts a predicate as happily as a
string. It looks odd, but it's exactly clingo's own data model, where a symbolic constant *is* a
zero-arity function. Unless you specifically need the unquoted form, we suggest sticking with plain
strings.

## Classical and default negation

If a bare atom is a wrinkle in what a field *holds*, negation is a wrinkle in the atom itself. ASP has two
kinds of negation, and they mean genuinely different things — worth pinning down the difference up front,
because they're easy to mix up. *Classical negation* makes a
**positive** claim that something is false: `-p` is the negated atom asserting that `p` does not hold. *Default negation*
(negation as failure) is weaker — `not p` means only that `p` is not *known* to be true, which isn't the
same as knowing it's false. Default negation is something you reach for in rule bodies, so it lives in
[Statements and Terms](statements.md#default-negation). Classical negation is a property of an atom itself, so it
belongs here, and it's what the rest of this section covers.

Classical negation is written as a unary minus on an atom: `-p`. The sign becomes part of the atom —
not a wrapper around it, and not a different predicate — mirroring clingo's own symbol model.
The `.negated` property reads it back:

```python
class Safe(Predicate):
    node: Field[str]
```

```python
>>> a = -Safe(node="b")
>>> a.render()
'-safe("b")'
>>> a.negated
True
```

Because the sign is just part of the atom, both signs of a predicate come back together from `atoms(Safe)`
when you read a solution — filter on `.negated` to tell them apart. Both are also declared
and shown in the rendered program:

```python
program = ASPProgram()
program.fact(Safe(node="a"), -Safe(node="b"))
```

```python
>>> print(program.render())
% Generated by aspalchemy ...
safe("a").
-safe("b").

#show.
#show -safe/1.
#show safe/1.
```

The two signs are a real contradiction: since `-safe("x")` asserts that `safe("x")` is false, any program
that derives both `safe("x")` and `-safe("x")` has no answer sets at all.

## The fine print

Back at the start we glossed over a few finer points of *declaring* a predicate; here they are collected
in one place. A predicate's arguments are exactly its `Field[...]` slots, in the order you declare them —
nothing else.
Any other annotation on the class is refused at creation, so a field you forgot to wrap in `Field[...]`
fails loudly right there rather than silently vanishing from the signature.

Genuinely non-argument data has two homes, neither touched by that rule: a `ClassVar` for a typed
constant, and a bare (unannotated) assignment for anything else:

```python
from typing import ClassVar

class Task(Predicate):
    name: Field[str]
    PRIORITY: ClassVar[int] = 1   # a typed class-level constant
    tag = "chore"                 # a bare attribute, not an argument

task = Task(name="dishes")
```

```python
>>> task.render()                 # only the Field slot is an argument
'task("dishes")'
>>> Task.field_names()
['name']
>>> Task.PRIORITY, task.tag
(1, 'chore')
```

Neither a field nor a `ClassVar` may take a name that would shadow one of `Predicate`'s own methods or
attributes; try it and you'll get an exception naming the collision, so you can never quietly break the
interface an atom relies on.

Two more conveniences carry over from dataclasses. A field may have a **default value** — validated
against its type when an instance is constructed without it, and subject to the usual rule that defaulted
fields come after undefaulted ones. And predicates support **inheritance**: a subclass appends its own
fields to the ones it inherits (you may add fields, but not redefine an inherited one), and a field typed
as a superclass accepts any of its subclasses.

## Predicate instances as Python values

One last property, and a convenient one: an atom is an ordinary Python value — assign it to a variable,
pass it around, reuse it. Two atoms compare
equal with `==` when they're the same predicate, the same sign, and carry the same data — and they hash to
match, so you can put them in sets and use them as dictionary keys:

```python
class Cell(Predicate):
    row: Field[int]
    col: Field[int]

assert Cell(row=1, col=2) == Cell(row=1, col=2)          # atoms compare as data
assert len({Cell(row=1, col=2), Cell(row=1, col=2)}) == 1  # sets and dict keys work
```

Atoms are immutable — they're frozen dataclasses — so to "change" one you build a modified copy. The right
tool is `copy.replace(atom, field=...)`, which produces a new instance with the given fields swapped and
preserves the classical-negation sign. Reach for that, not `dataclasses.replace`, which looks equivalent
but silently drops the sign.
