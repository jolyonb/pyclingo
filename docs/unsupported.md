# What We Don't Support

*The opinionated-subset story: philosophy exclusions, better-errors, strictness, multi-shot honesty — the single home for refusals.*

ASPAlchemy deliberately does not admit everything gringo does. The net is
one-sided by design: every refusal is either a certain clingo rejection or a
construct that is nearly always a mistake, and each refusal says what you
probably meant instead. This page is the single home for the *what* and the
*why* — each entry names the exclusion, gives the honest reason, and links the
supported spelling.

## An opinionated subset is a feature

A library that emits a language it doesn't fully admit owes you two things:
the boundary must be principled, and there must be a door through it. The
boundary is principled because it is one-sided — nothing on this page is a
construct that clingo accepts, ASPAlchemy could model cleanly, and we simply
didn't get to. Each exclusion is here because clingo would reject it, because
clingo would silently misread it, or because a design decision (recorded
below) keeps it out. And the door exists: everything excluded can be written
verbatim with `raw_asp()` — the *how* lives on
[Escape Hatches](escape-hatches.md).

One nearby topic that reads like an exclusion but isn't: clingo's arithmetic
semantics differ from Python's in four pinned places — rounding on negative
division and modulo, negative exponents, 32-bit wraparound, and division by
zero. All fully supported; they just don't mean quite what a Python reader
expects. See [Arithmetic](math.md).

## Excluded by philosophy

These constructs are outside the typed model on purpose.

**Disjunctive heads** (`a ; b :- c.`). The generate step in ASPAlchemy is
spelled `Choice`: `Choice(...).at_least(1)` covers what a disjunctive head is
nearly always used for, and `raw_asp()` covers the rest. Trying to build one
(`p | q` on atoms, or a conditional literal in a head) raises with exactly
that advice.

**Theory atoms** (`&diff { ... }`). Theory atoms belong to clingo's
extension systems — clingo-dl, clingcon, custom propagators — each with its
own grammar and solver machinery. None of that is modeled in the typed
layer. The underlying `clingo.Control` is reachable at `grounded.control`,
which names theory atoms among its at-your-own-risk internals — see
[Solver options and the raw Control](escape-hatches.md#solver-options-and-the-raw-control).

**Anonymous tuples** (`p((1, 2))`). Valid clingo, but a tuple term is
unnamed ad-hoc structure: nothing says what the positions mean, so the typed
layer has nowhere to hang a schema. The refusal fires on the way in and again
when reading a raw block's output, and both say the same thing — "wrap it in
a named predicate (`pair(1, 2)` instead of `(1, 2)`)". A nested predicate
field (`Field[Pair]`) carries the identical term with a schema, typing, and
readable output — see
[Declaring predicates](predicates.md#declaring-predicates).

**Meta-directives.** `#include` is refused because you already have a
module system: your program is Python, so imports, functions, and loops are
the modularity story. `#program` and `#external` belong to the multi-shot
workflow, which is honestly unmodeled — the next section. All three are
refused inside `raw_asp()` blocks too, each with a redirect
([Blocked directives](escape-hatches.md#blocked-directives)).

**Scripting and `@`-functions — unmodeled, not refused.** A typed rule never
contains an `@`-call: scripting sits outside the typed layer. But it is
fully supported through the hatch — `raw_asp()` text may carry `@f(X)` terms
and a self-contained `#script` block, and `ground(context=...)` supplies the
Python object whose methods back the calls.
[Calling Python during grounding](escape-hatches.md#calling-python-during-grounding)
is the full story.

## Multi-shot solving: a future design project

clingo's incremental workflow — `#program` parts grounded onto one Control
across successive solves, the iterative-deepening and planning idiom — is
entirely unmodeled: ASPAlchemy grounds a single base part, and `raw_asp()`
rejects `#program` outright. Supporting it is a genuine design project, not a
feature bolt-on. It breaks `GroundedProgram`'s core promise — an immutable
snapshot that solves the same program forever — in favor of a handle that
accretes state, and it needs real answers for how segments map to parts, what
part parameters look like in typed Python, and what the teaching errors
become when statements land in never-grounded parts.

The interim answer covers more than you might expect:
[ground() + assumptions](solving.md#ground-once-solve-many) makes repeated
questions against one program cheap — the incremental 80%. `#external`,
multi-shot's usual companion for per-step toggles, is deliberately undecided
rather than refused forever: assumptions already cover much of that use
today, so support will be argued from a concrete need, not from
completeness.

## Cost-budget enumeration

clasp's `--opt-mode=enum,N` — enumerate every model with cost within a bound
— is not modeled. With a single priority tier you don't need it: the bound
*is* a hard constraint, so state the budget as a `Sum` guard and iterate
plain `solve()`:

```python
from itertools import combinations

from aspalchemy import ANY, ASPProgram, Choice, Field, Predicate, Sum, Variable

class Item(Predicate, show=False):
    """An available item and what it costs."""
    name: Field[str]
    cost: Field[int]

class Picked(Predicate):
    """The solver put this item in the basket."""
    name: Field[str]

costs = {"anchovies": 1, "basil": 2, "capers": 3}
BUDGET = 3

program = ASPProgram()
program.fact(*(Item(name=n, cost=c) for n, c in costs.items()))

N, C = Variable("N"), Variable("C")
program.choose(Choice(Picked(name=N), condition=Item(name=N, cost=ANY)))

# The budget is a hard constraint, not an objective:
program.forbid(Sum((C, N), condition=[Picked(name=N), Item(name=N, cost=C)]) > BUDGET)
```

The budget lands in the generated ASP as a plain constraint — no `#minimize`,
nothing for `--opt-mode` to bound:

```python
>>> print(program.render())
% Generated by aspalchemy ...
item("anchovies", 1).
item("basil", 2).
item("capers", 3).
{ picked(N) : item(N, _) }.
:- #sum{ C, N : picked(N), item(N, C) } > 3.

#show.
#show picked/1.
```

So plain `solve()` enumerates every basket inside the budget, and only those.
Enumeration order isn't promised, but the *set* of models is — here it is,
collected and sorted:

```python
>>> baskets = {frozenset(a.name for a in model.atoms(Picked)) for model in program.solve()}
>>> sorted(sorted(basket) for basket in baskets)
[[], ['anchovies'], ['anchovies', 'basil'], ['basil'], ['capers']]
```

The empty basket, three singletons, and the one affordable pair — exactly the
baskets a brute-force Python check admits, no more:

```python
affordable = {
    frozenset(combo)
    for r in range(len(costs) + 1)
    for combo in combinations(costs, r)
    if sum(costs[n] for n in combo) <= BUDGET
}
assert baskets == affordable
```

With multiple priority tiers the flag means something sharper than it looks:
the bound is **lexicographic**. Probed against clingo 5.8: a model
costing (1, 5) is admitted under bound (2, 3) — tier one beat its
bound, so later tiers never mattered. That beat-or-tie cascade is the one
form genuinely clunky to hand-encode, and it is why this entry stays on the
watch list rather than the roadmap: it gets built when a real
lexicographic-budget need appears, not before. For stating and solving
objectives themselves, see [Optimization](solving.md#optimization).

## Better errors, not restrictions

These are not subset boundaries. Each construct here is something clingo
would reject or silently misread anyway — ASPAlchemy just fails at your
Python line, with the diagnosis, instead of at grounding or (worse) never.

**Bare pools as rule elements.** A pool standing alone in a rule is a clingo
syntax error. Pools belong inside predicate arguments and on the right of
comparisons — [Pools and ranges](rules.md#pools-and-ranges).

**`Number(True)`.** A boolean is never a valid ASP term, but `bool`
subclasses `int`, so it is exactly the kind of value that slips through
integer checks unnoticed — and both plausible outcomes (silent coercion to
`1`, or the literal text `True`, which clingo does not read as a number) mean
something you didn't write. Refused with a `TypeError` at construction.

**Negated pool comparisons.** `not X = (2; 3)` does not mean "not in": pools
expand disjunctively, so the negated form is true for every `X` — there is
always some pool member `X` differs from. The teaching error spells the fix:

```python
>>> from aspalchemy import Not
>>> X = Variable("X")
>>> Not(X.in_((2, 3)))
Traceback (most recent call last):
  ...
ValueError: Negating a pool comparison does not mean 'not in': pools expand disjunctively, ... Write separate conditions instead, e.g. X != 2, X != 3
```

The same disjunctive expansion is why `require()` refuses pool comparisons:
`require()` on a comparison inverts it into a constraint, and a pool comparison
has no inverse.

**Aggregates on both sides of one comparison.**
`#count{ ... } < #count{ ... }` is a clingo syntax error. Refused at
construction, with the workaround in the message: bind one aggregate to a
variable in a separate rule.

## Deliberate strictness

Everything in the previous section fails in clingo too. This section is
different: valid clingo we refuse anyway, because each construct is nearly
always a mistake.
Every refusal is a teaching error naming the supported spelling — and per
the site's single-demo rule, the executable demos live in the guide pages
linked below, not here.

**`_X` don't-warn variables.** gringo allows underscore-prefixed names to
suppress its own warnings; ASPAlchemy's rule is narrower — one underscore
means anonymous, full stop. Use `ANY` for don't-care positions.

**Singleton variables.** A variable used exactly once in a rule is usually a
typo, so it fails a lint here (gringo itself stays silent). The demo and the
`ASPProgram(allow_singletons=True)` switch live in
[Variables](rules.md#variables).

**Braces in rule bodies.** `2 { p(X) } 4` in a body is a cardinality *test*,
not a choice — same syntax, different semantics. Spell tests as `Count`
comparisons, which ground identically; the demo lives in
[Cardinality tests are not choices](choices-and-aggregates.md#cardinality-tests-are-not-choices).

**Negated heads.** `not p :- body.` derives nothing: gringo itself rewrites
it into a constraint before grounding — probed against clingo 5.8,
`not p :- q.` grounds as `:- q, not not p.`, and in a
constraint body `not not p` is equivalent to `p`. It is alternative syntax
for `forbid(*body, p)`, already spelled; the head position misleads by
looking like it derives something.

**Plain `solve()` on an optimizing program.** Refused with a teaching error
rather than silently enumerating the answer sets the objective was supposed
to rank: solve it with `optimize()`, or pass `ignore_optimization=True` to
enumerate as if there were no objective.
[Optimization](solving.md#optimization) owns the contract and the demo.

## The escape hatch

Every exclusion on this page shares one exit: `raw_asp()` accepts verbatim
clingo text, with a `predicates=` seatbelt so the atoms a raw block derives
still round-trip as typed instances. The full treatment — the seatbelt, the
lexical rules, the blocked directives, grounding contexts, and solver
options — is [Escape Hatches](escape-hatches.md).
