# Solving and Results

*Model streams, typed reads, brave/cautious, optimization, ground()+assumptions, unsat cores, statistics, scale honesty.*

## The model stream

The examples on this page need a program to solve. Here is a small one — the
verbs are covered in [Rules and Terms](rules.md); if this is your first
aspalchemy program, start with [Your First Program](getting-started.md#solve-and-read-back)
instead.

```python
from aspalchemy import Field, Predicate, PredicateArg

class Person(Predicate):
    name: Field[PredicateArg]
    age: Field[PredicateArg]

john = Person(name="john", age=30)
mary = Person(name="mary", age=25)
```

```python
from aspalchemy import ANY, ASPProgram, Variable

program = ASPProgram()
X, Y = Variable("X"), Variable("Y")
Adult = Predicate.define("adult", ["name"])

# Facts
program.fact(john)
program.fact(mary)

# Rules
program.when(Person(name=X, age=Y), Y >= 18).derive(Adult(name=X))

# Constraints
program.forbid(Person(name=ANY, age=Y), Y < 0)
```

`solve()` returns a `SolveResult`: a lazy, unbounded stream of `Model`
objects. Rendering, grounding — instantiating every rule over the actual
data, the step that turns your program into the solver's input — and their
error checks run eagerly at the call; only model enumeration is lazy —
clasp, clingo's search engine, computes the next model when you resume, so
nothing runs ahead of your consumption. Take what you need:
`first()` for one answer, `itertools.islice` for N, a for-loop with `break`
for a condition. A whole-stream read (`list(result)`, a bare for-loop)
enumerates *every* model, which an underconstrained program can make
effectively endless. This program has no choices, so it provably has exactly
one answer set and enumerating it all is safe — and the exact transcript
below is legitimate:

```python
>>> result = program.solve()
>>> for model in result:
...     for adult in sorted(model.atoms(Adult), key=lambda atom: atom.render()):
...         print(adult)
adult("john")
adult("mary")
>>> result.satisfiable and result.exhausted and result.models_yielded == 1
True
```

`satisfiable`, `exhausted`, and `models_yielded` update as models arrive and
finalize when iteration ends on any path — natural exhaustion, an explicit
`close()`, or leaving a `with`-block. `first()` is the one-answer sugar: it
returns the first model and closes the search, raising `UnsatisfiableError`
when there is no model at all. If UNSAT is an expected outcome for your
program, use `next(iter(result), None)` instead, which gives `None` rather
than raising.

```python
from itertools import islice
from aspalchemy import Choice, Field

class Item(Predicate, show=False):
    name: Field[str]

class Chosen(Predicate):
    name: Field[str]

N = Variable("N")
menu = ASPProgram()
menu.fact(*(Item(name=n) for n in ["a", "b", "c"]))
menu.choose(Choice(Chosen(name=N), condition=Item(name=N)).at_least(1))
```

```python
>>> result = menu.solve()
>>> some = list(islice(result, 2))   # take two models; the rest are never computed
>>> len(some), result.models_yielded, result.exhausted
(2, 2, False)
>>> result.close()                   # finalizes the flags and statistics
>>> len(list(menu.solve()))          # all non-empty subsets of three items
7
>>> first = menu.solve().first()     # any one of the seven
>>> 1 <= len(first.atoms(Chosen)) <= 3
True
```

Every call to `solve()` renders and grounds a fresh clingo Control, so
repeated solves on one program never interfere, and statements added after a
solve simply take effect on the next call. (When you want to pay for
grounding once and solve many times, see
[Ground once, solve many](#ground-once-solve-many).)

The timeout contract, stated once here: everywhere on this page, `timeout=`
is a wall-clock limit in seconds, counted from the start of iteration. On a
model stream, timing out is quiet — the models found so far have already
been yielded and `exhausted` stays `False`, since every yielded model was a
true answer. A timeout before *any* model raises `TimeoutError`, because a
silent empty stream would read as unsatisfiable. (Consequence refinements
are stricter — see [Brave and cautious](#brave-and-cautious).)

## Reading models

Every result type on this page — `Model`, the consequences, `Optimum` — is
an `AtomCollection`: one shared reading surface that makes no claim about
what the atoms *mean* — only the subclass says that (a Model's atoms are one
answer set; a Consequences' are a statement about every answer set). `atoms(Cls)` returns
typed instances of one predicate class, `atoms()` with no argument returns
everything, membership (`atom in model`) and iteration work as you'd expect.
Reads are plain Python: a `Field[str]` field comes back as a real `str`, a
`Field[int]` as a real `int`, and a `Field[PredicateArg]` slot the same way — the
full field contract lives in
[Writes and reads](predicates.md#writes-and-reads).

```python
>>> model = menu.solve().first()
>>> names = sorted(atom.name for atom in model.atoms(Chosen))
>>> all(isinstance(name, str) for name in names)      # typed reads: plain str
True
>>> bool(names) and set(names) <= {"a", "b", "c"}     # which items came back is the solver's call
True
```

Hidden atoms (`show=False` and never shown) are never read back into results
at all — skipping them is what keeps model reads fast — so asking for a
hidden class raises with the remedy instead of returning an `[]` that would
read as "none were derived":

```python
>>> model.atoms(Item)               # Item is show=False
Traceback (most recent call last):
  ...
ValueError: item/1 is hidden (show=False and never shown): hidden atoms are not read back into results ... show() the class, or define it with show=True, to read it.
```

Lookup is by exact class (an
[`in_namespace()` clone](predicates.md#names-namespaces-and-visibility) is a
distinct class), and both signs of a classically negated predicate come back
from the same `atoms(Cls)` call — filter on `.negated` if your program uses
[classical negation](predicates.md#classical-negation).

## Brave and cautious

Two questions you can ask without enumerating every model: what is
*possible* — true in at least one answer set — and what is *certain* — true
in every answer set. `brave()` computes the union of all answer sets,
`cautious()` the intersection; each returns eagerly:

```python
>>> possible = menu.brave()                             # true in AT LEAST ONE answer set
>>> sorted(atom.name for atom in possible.atoms(Chosen))
['a', 'b', 'c']
>>> possible.complete                                   # a PROOF the refinement finished
True
>>> certain = menu.cautious()                           # true in EVERY answer set
>>> certain.complete
True
>>> certain.atoms(Chosen)   # something must be chosen, but no one item is forced
[]
>>> len(certain.path) >= 1                              # every approximation, kept as receipts
True
```

`BraveConsequences` and `CautiousConsequences` carry their evidence: `.path`
holds every successive approximation clasp computed (brave grows toward the
union, cautious shrinks toward the intersection), and `.complete` is a proof
of exhaustion, not a guess. A bounded run — `timeout=` seconds or
`max_iterations=` refinement steps — returns an *incomplete* result whose
knowledge is one-sided: every atom a partial brave result contains is
certified possible (absence proves nothing yet), and every atom a partial
cautious result *lacks* is certified not-forced (presence proves nothing
yet). Both eager verbs raise `UnsatisfiableError` when the program has no
answer set, carrying the [unsat core](#unsat-cores) and the solve's messages.

For stepwise control, `brave_iter()`/`cautious_iter()` on a
[grounding](#ground-once-solve-many) return `RefinementSteps`: iterate for
successive approximations and stop the moment your question is answered —
each step is a full solver search, so control between steps is control over
real work. Iteration ending naturally means the last approximation is the
true union/intersection; zero yields means unsatisfiable; and a timeout
raises `TimeoutError` from within iteration, so a timed-out refinement can
never impersonate a completed one.

On an optimizing program, all four verbs refuse with a teaching error: the
refinement would be computed against the solver's cost-descent path, not the
set of answer sets. Pass `ignore_optimization=True` to refine over *all*
answer sets as if there were no objective (see
[Optimization](#optimization), which owns that switch).

## Optimization

Objectives enter the program two ways. `minimize()`/`maximize()` state an
objective directly: a weight, the tuple terms that make each contribution
distinct, an optional `condition=`, and a `priority=` tier (higher tiers
dominate lower ones lexicographically). `penalize()` is the soft-constraint
spelling — a `forbid()` that charges instead of forbidding: each ground
match of the conditions adds `weight` to the cost, rendered as a weak
constraint (`:~ ... [w@p, terms]`). The two are semantically identical, so
the spelling is intent: `penalize()` for soft constraints, `minimize()` for
objectives. `penalize()` also works as a `when()` closer, like `forbid()`.

Solving an objective is `optimize()`, which returns the best answer set as
an `Optimum` — a model carrying its cost and its certificate:

```python
class Task(Predicate, show=False):
    name: Field[str]

class Slot(Predicate, show=False):
    n: Field[int]

class Assigned(Predicate):
    task: Field[str]
    slot: Field[int]

T, S = Variable("T"), Variable("S")
chores = ASPProgram()
chores.fact(*(Task(name=t) for t in ["wash", "dry", "fold"]))
chores.fact(*(Slot(n=s) for s in [1, 2, 3]))
chores.when(Task(name=T)).derive(
    Choice(Assigned(task=T, slot=S), condition=Slot(n=S)).exactly(1)
)
chores.penalize(Assigned(task=T, slot=S), weight=S, terms=[T])  # earlier slots are cheaper

best = chores.optimize()
```

```python
>>> best.cost                                      # all three tasks land in slot 1
(3,)
>>> best.proven                                    # optimality was PROVED, not assumed
True
>>> {atom.slot for atom in best.atoms(Assigned)}
{1}
```

`cost` has one entry per surviving priority level, highest first (a
maximization's cost is reported negated — lower is better in every sense).
`.path` holds every emission of the descent, each a genuine answer set —
so an interrupted search's best is still a real solution: a `timeout=` or
`max_iterations=` cap returns the best model found so far with
`proven=False`, the anytime reading, and `TimeoutError` fires only when the
deadline lands before any model at all. `optimize(all_optima=True)` continues
past the optimality proof and collects *every* certified optimum in
`.optima` (with `.complete` true, `len(optimum.optima) == 1` answers
uniqueness). `strategy=OptStrategy.USC` swaps clasp's algorithm — often
dramatically faster when branch and bound stalls, at the price of a sparse
emission stream — and `bound=` starts the search from a known cost, with the
caveat that a too-tight bound is reported as unsatisfiable (clasp cannot tell
the difference). The stepwise form, `optimize_iter()`, lives on a
[grounding you keep](#ground-once-solve-many) and yields each strictly-better
`CostedModel` as it is found.

Plain `solve()` on an optimizing program refuses with a teaching error,
rather than silently enumerating answer sets the objective was supposed to
rank:

```python
>>> chores.solve()
Traceback (most recent call last):
  ...
ValueError: This program optimizes (#minimize/#maximize present). Solve it with optimize(), or pass ignore_optimization=True to enumerate answer sets as if there were no objective.
>>> len(list(chores.solve(ignore_optimization=True)))   # three slots per task, objective ignored
27
```

`ignore_optimization=True` (clasp's `opt-mode=ignore`) enumerates answer
sets as if the program had no objective, for that solve only — and it
requires an objective to ignore, raising on a program without one rather
than passing vacuously. If what you actually want is every model within a
cost budget, see
[Cost-budget enumeration](unsupported.md#cost-budget-enumeration).

## Ground once, solve many

`ground()` renders and grounds the program once and returns a
`GroundedProgram`: an independent, immutable snapshot that solves exactly
that program forever, unaffected by later mutation of the `ASPProgram` it
came from — like a compiled regex and its pattern. Every verb above lives on
it (`solve`, `brave`, `cautious`, `optimize`), each eager verb has a lazy
twin (`brave_iter`, `cautious_iter`, `optimize_iter` — the
findall/finditer pairing), and assumptions parameterize any of them per
call: a grounded atom assumes it true, `~atom` assumes it false, for that
solve only.

```python
>>> grounding = menu.ground()       # grounding is paid once
>>> len(list(grounding.solve()))
7
>>> len(list(grounding.solve(assumptions=[Chosen(name="a")])))    # the subsets containing "a"
4
>>> len(list(grounding.solve(assumptions=[~Chosen(name="a")])))   # the non-empty subsets of {"b", "c"}
3
```

Assumptions are also accepted directly by `ASPProgram.solve()` and the other
program-level verbs — the grounding is not what enables them, it is just
where asking many questions of one program gets cheap, since each
program-level call re-grounds from scratch.

One contract, enforced loudly: solves on a grounding are sequential. A
Control cannot run overlapping searches, so starting a new solve while a
previous result is unconsumed raises instead of silently corrupting either:

```python
>>> open_result = grounding.solve()
>>> grounding.solve()
Traceback (most recent call last):
  ...
RuntimeError: The previous solve on this grounding is still open; a Control cannot run overlapping searches. Consume the previous result, close() it, leave its with-block, or call abandon() on this grounding.
>>> open_result.close()                 # or consume it, or leave its with-block
>>> len(list(grounding.solve()))        # the snapshot solves the same program forever
7
```

`ground()` + assumptions is also the interim answer to incremental solving:
true multi-shot (clingo's `#program` parts) is honestly
[a future design project](unsupported.md#multi-shot-solving-a-future-design-project).

## Unsat cores

When a solve under assumptions comes back UNSAT, the search leaves evidence:
the set of assumptions clasp reports as jointly unsatisfiable. It rides the
exception as `UnsatisfiableError.unsat_core`, in the shapes the assumptions
were given:

```python
from aspalchemy import UnsatisfiableError

class Guest(Predicate, show=False):
    name: Field[str]

class Invited(Predicate):
    name: Field[str]

G = Variable("G")
party = ASPProgram()
party.fact(*(Guest(name=g) for g in ["alice", "bob", "cara"]))
party.choose(Choice(Invited(name=G), condition=Guest(name=G)))
party.forbid(Invited(name="alice"), Invited(name="bob"))    # rivals

grounded = party.ground()
try:
    grounded.solve(assumptions=[Invited(name="alice"), Invited(name="bob")]).first()
    raise AssertionError("conflicting assumptions must be UNSAT")
except UnsatisfiableError as e:
    assert e.unsat_core                                     # the evidence rides the exception
    assert set(e.unsat_core) <= {Invited(name="alice"), Invited(name="bob")}
```

The same evidence is available as `SolveResult.unsat_core` once a search has
*proven* unsatisfiability (`None` before then and for satisfiable programs;
`()` when UNSAT needed no assumptions at all), and the eager verbs —
`cautious()`, `brave()`, `optimize()` — carry it on their
`UnsatisfiableError` too. It is *a* core, not necessarily a minimal one:
clasp promises it contains a conflict, nothing more. A core only exists
relative to assumptions — which is why this section lives beside the
grounding story, where assumption-driven questioning is the workflow.

## Statistics and messages

Every search handle snapshots clingo's statistics as it finishes:
`.statistics` is the raw dict (a copy, plus a `wall_time` key spanning the
handle's creation to the end of iteration), and `format_statistics()`
renders it in clingo's native output style. The eager results (`Optimum`,
the consequences) carry the same snapshot, so nothing is lost by not using
the `_iter` twin.

```python
result = party.solve()
models = list(result)
assert result.statistics is not None and "wall_time" in result.statistics
assert result.format_statistics().startswith("Models")

assert all(model.messages == () for model in models)   # solve-phase diagnostics, usually empty
```

Clingo's own statistics reflect the most recent search on the shared
Control — snapshotting at finish is what makes each handle's numbers its
own. Diagnostics emitted *during* the solve phase never halt solving (the
`stop_on_log_level` threshold applies to parsing and grounding only); they
are captured on the handle's `.messages` and, per model, on
`Model.messages`. What the messages look like, and how grounding
diagnostics map back to your Python source, is covered in
[Clingo's messages](diagnostics.md#clingos-messages).

## A note on scale

An honest note: the model-read path is tuned for puzzle-sized models. Atom
equality goes through rendering and membership checks are linear scans, so
reading models is comfortable at 10^4 atoms and will hurt at 10^5–10^6.
The one lever that matters is visibility: hidden atoms are never read back
at all — hundreds of thousands of scaffolding atoms cost nothing if you
`hide()` them — so show only what you actually consume.
