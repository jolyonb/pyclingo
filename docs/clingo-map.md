# Clingo to ASPAlchemy

*Translation table: every clingo construct → its spelling here or its refusal link; CI-pinned by a trailing block of verified transcripts.*

You already write clingo. This page answers, construct by construct, how each
thing you write is spelled in aspalchemy — or that it is deliberately refused,
with a link to [why](unsupported.md). Every supported row links the guide page
that owns it, and the [Receipts](#receipts) section shows the load-bearing
renderings as executed transcripts, so if a table entry drifts from the
library, CI breaks before you do. For clingo's own semantics, the
[Potassco guide](https://potassco.org/doc/) remains the reference — this page
only maps spellings.

Refused constructs are marked **refused** and never re-argued here:
[What We Don't Support](unsupported.md) is the single home for the reasoning,
and [Escape Hatches](escape-hatches.md) covers `raw_asp()` when you need a
construct anyway.

## Terms and literals

| clingo | aspalchemy | details |
|--------|------------|---------|
| `X`, `Node` (variables) | `Variable("X")`, or `V.X` for inline use | [Variables](rules.md#variables) |
| `_` (don't-care) | `ANY` | [Variables](rules.md#variables) |
| `_X` (named don't-warn variable) | **refused** — use `ANY` | [Deliberate strictness](unsupported.md#deliberate-strictness) |
| `42` | Python `int`, auto-coerced (`Number` is the explicit form) | [Constants and extremes](rules.md#constants-and-extremes) |
| `"hello"` | Python `str`, auto-coerced — a `str` always means a quoted ASP string | [One text type](predicates.md#bare-atoms-and-the-one-text-type-design) |
| `n` (symbolic constant / bare atom) | a zero-arity predicate: `Predicate.define("n", [])()` | [Bare atoms](predicates.md#bare-atoms-and-the-one-text-type-design) |
| `1..5` | `RangePool(1, 5)` or `pool(range(1, 6))` | [Pools and ranges](rules.md#pools-and-ranges) |
| `(a; b; c)` | `ExplicitPool([...])` or `pool([...])` | [Pools and ranges](rules.md#pools-and-ranges) |
| `X = 1..5` in a body | `X.in_(RangePool(1, 5))` — also accepts a Python `range`, list, or tuple | [Pools and ranges](rules.md#pools-and-ranges) |
| `X = Y + 1` (binding assignment in a body) | `X == Y + 1` — a comparison; the equality binds the variable, so it satisfies the safety check | [Comparisons](rules.md#comparisons) |
| `p(X) : q(X)` (conditional literal in a body) | `ConditionalLiteral(P(x=X), Q(x=X))` | [Conditional literals](rules.md#conditional-literals) |
| `#sup` / `#inf` | `SUP` / `INF` | [Constants and extremes](rules.md#constants-and-extremes) |
| `#const n = 5.` | `program.define_constant("n", 5)` — returns the `DefinedConstant` term to use in rules | [Constants and extremes](rules.md#constants-and-extremes) |
| `p(f(X, Y))` (nested function terms) | predicate-valued fields: `Field[F]` — nested atoms travel as typed compound terms | [Declaring predicates](predicates.md#declaring-predicates) |
| `p((1, 2))` (anonymous tuples) | **refused** (teaching error) — wrap in a named predicate: `pair(1, 2)`, i.e. a nested `Field[Pair]` | [Excluded by philosophy](unsupported.md#excluded-by-philosophy) |

## Facts, rules, constraints

| clingo | aspalchemy | details |
|--------|------------|---------|
| `p(3).` | `program.fact(P(x=3))` — ground atoms only, any number per call | [The verbs](rules.md#the-verbs) |
| `p(a).` (symbolic-constant argument) | the argument is a zero-arity atom: `fact(P(x=a()))` with `a = Predicate.define("a", [])` — a Python `str` would render the quoted string `"a"`, a different value | [Bare atoms](predicates.md#bare-atoms-and-the-one-text-type-design) |
| `h :- b1, b2.` | `program.when(b1, b2).derive(h)` | [The verbs](rules.md#the-verbs) |
| `:- b1, b2.` | `program.forbid(b1, b2)` | [The verbs](rules.md#the-verbs) |
| a comparison that must hold | `program.require(cmp)` — renders as a constraint forbidding the complement | [The verbs](rules.md#the-verbs) |
| `% comment` | `program.comment(...)`, `section(...)`, `blank_line()` | [Organizing output](rules.md#organizing-output) |
| `a; b :- c.` (disjunctive heads) | **refused** | [Excluded by philosophy](unsupported.md#excluded-by-philosophy) |

## Negation

| clingo | aspalchemy | details |
|--------|------------|---------|
| `not p(X)` | `Not(P(x=X))` or `~P(x=X)` | [Default negation](rules.md#default-negation) |
| `not not p(X)` | `~~P(x=X)` — preserved, not collapsed (stable-model semantics) | [Default negation](rules.md#default-negation) |
| `not X != Y` (negated plain comparison) | `~(X != Y)` — normalized to the complement `X = Y` at construction, gringo's own rewrite done visibly | [Default negation](rules.md#default-negation) |
| `-p(X)` (classical negation) | `-P(x=X)` — unary minus on the atom; the sign is part of the atom | [Classical negation](predicates.md#classical-negation) |
| `-p` in output declarations | `-P` on the class (a `NegatedSignature`), e.g. in `raw_asp(predicates=[P, -P])` | [The predicates= seatbelt](escape-hatches.md#the-predicates-seatbelt) |
| `not p :- b.` (negated head) | **refused** (teaching error) — gringo rewrites it into a constraint anyway; spell `forbid(b, p)` | [Deliberate strictness](unsupported.md#deliberate-strictness) |
| `not X = (2; 3)` (negated pool comparison) | **refused** (teaching error) — pools expand disjunctively; spell the exclusion as separate conditions: `X != 2, X != 3` (`X.in_(...)` covers the positive case) | [Better errors](unsupported.md#better-errors-not-restrictions) |

## Choices and cardinality

| clingo | aspalchemy | details |
|--------|------------|---------|
| `{ h : c } = 1 :- b.` | `program.when(b).derive(Choice(h, condition=c).exactly(1))` | [Choice rules](choices-and-aggregates.md#choice-rules) |
| `2 { h : c } 4` (head bounds) | `Choice(h, condition=c).at_least(2).at_most(4)` | [Choice rules](choices-and-aggregates.md#choice-rules) |
| `{ p(X) : q(X) }.` (bare choice) | `program.choose(Choice(P(x=X), condition=Q(x=X)))` | [Choice rules](choices-and-aggregates.md#choice-rules) |
| `2 { p(X) } 4` in a **body** (cardinality test) | **refused** (teaching error) — a body-brace test is not a choice; spell it as `Count` comparisons, which ground identically | [Cardinality tests are not choices](choices-and-aggregates.md#cardinality-tests-are-not-choices) |

## Aggregates

| clingo | aspalchemy | details |
|--------|------------|---------|
| `#count{...}` / `#sum{...}` / `#sum+{...}` / `#min{...}` / `#max{...}` | `Count` / `Sum` / `SumPlus` / `Min` / `Max` — tuple terms and conditions as arguments, more elements via `add()` | [Aggregates](choices-and-aggregates.md#aggregates) |
| `#count{...} > 3` (one-sided guard) | one comparison: `Count(...) > 3` | [Guards, the right way](choices-and-aggregates.md#guards-the-right-way) |
| `2 <= #count{...} <= 4` (two-sided guard) | two comparisons over the same aggregate: `Count(...) >= 2, Count(...) <= 4` — grounds to byte-identical aspif, receipt included | [Guards, the right way](choices-and-aggregates.md#guards-the-right-way) |
| aggregates on both sides of one comparison | **refused** — a clingo syntax error anyway; bind one to a variable in a separate rule | [Better errors](unsupported.md#better-errors-not-restrictions) |

## Arithmetic

Same tree, different spellings — Python builds the expression with Python
operators, and the renderer emits clingo's. Semantics (division sign quirks,
precedence, overflow) live in [Arithmetic](math.md).

| clingo | aspalchemy | details |
|--------|------------|---------|
| `x / y` (integer division) | `x // y` | [Arithmetic](math.md#operator-table) |
| `x \ y` (modulo) | `x % y` | [Arithmetic](math.md#operator-table) |
| `x ? y` (bitwise or) | `x \| y` | [Arithmetic](math.md#operator-table) |
| `~x` (bitwise complement) | `Compl(x)` — `~` itself is reserved for default negation | [Arithmetic](math.md#operator-table) |
| `\|x\|` (absolute value) | `abs(x)` | [Arithmetic](math.md#operator-table) |

`+`, `-`, `*`, `**`, `&`, `^`, and all six comparison operators are spelled as
in Python and render as themselves.

## Optimization

| clingo | aspalchemy | details |
|--------|------------|---------|
| `#minimize{ w@p, t : c }.` | `program.minimize(w, *terms, condition=c, priority=p)` | [Optimization](solving.md#optimization) |
| `#maximize{ w@p, t : c }.` | `program.maximize(w, *terms, condition=c, priority=p)` | [Optimization](solving.md#optimization) |
| `:~ b1, b2. [w@p, t]` (weak constraint) | `program.penalize(b1, b2, weight=w, terms=[...], priority=p)` — also a `when()` closer | [Optimization](solving.md#optimization) |
| `@p` priority tiers | `priority=` on any of the above | [Optimization](solving.md#optimization) |
| optimization run | `program.optimize()` → `Optimum` | [Optimization](solving.md#optimization) |
| `--opt-mode=ignore` / plain solving of an optimizing program | `solve(ignore_optimization=True)` — plain `solve()` refuses with a teaching error | [Optimization](solving.md#optimization) |
| `--opt-mode=enum,N` (cost-budget enumeration) | **refused** — single tier is a `solve()` with a hard `Sum` constraint | [Cost-budget enumeration](unsupported.md#cost-budget-enumeration) |

## Directives

| clingo | aspalchemy | details |
|--------|------------|---------|
| `#show p/2.` | shown by default; `show=False` on the class hides, `program.show()` / `hide()` override per class | [Names and visibility](predicates.md#names-namespaces-and-visibility) |
| `#show p(X) : cond.` (conditional show) | `program.show_when(ConditionalLiteral(head, condition))` | [Names and visibility](predicates.md#names-namespaces-and-visibility) |
| `#const` | `define_constant()` — refused inside raw blocks, same redirect | [Constants and extremes](rules.md#constants-and-extremes) |
| `#project` / `#heuristic` | via `raw_asp()` — silently inert until the matching `grounded.control` knob is set | [Solver options](escape-hatches.md#solver-options-and-the-raw-control) |
| `#script (python) ... #end.` | supported inside ONE self-contained `raw_asp()` block | [Lexical rules](escape-hatches.md#blocks-are-lexically-self-contained) |
| `@f(X)` terms | supported through the hatch: `raw_asp()` text + `ground(context=obj)` — `@stone(...)` calls `context.stone(...)` | [Calling Python during grounding](escape-hatches.md#calling-python-during-grounding) |
| `#defined p/1.` | supported via `raw_asp("#defined p/1.")` — the default `stop_on_log_level=INFO` turns gringo's body-only-atom info into a loud `GroundingError`, and `#defined` is the preferred fix | [Clingo's messages](diagnostics.md#clingos-messages) |
| `#include` | **refused**, in raw blocks too — your program is Python, so imports and functions are the modularity story | [Excluded by philosophy](unsupported.md#excluded-by-philosophy) |
| `#program` / `#external` | **refused**, in raw blocks too — multi-shot is honestly unmodeled | [Multi-shot solving](unsupported.md#multi-shot-solving-a-future-design-project) |
| `&diff{...}` (theory atoms) | unmodeled in the typed layer; `grounded.control` exposes clingo's internals (configuration, externals, theory atoms, observers) at your own risk | [Excluded by philosophy](unsupported.md#excluded-by-philosophy) |

## Solving modes

| clingo | aspalchemy | details |
|--------|------------|---------|
| `--models 0` (enumerate all) | iterate `solve()` — the stream is lazy and unbounded; take what you need | [The model stream](solving.md#the-model-stream) |
| `--enum-mode=brave` / `--enum-mode=cautious` | `brave()` / `cautious()` — note the one-sided partial-certification contract | [Brave and cautious](solving.md#brave-and-cautious) |
| optimization run | `optimize()`; stepwise via `optimize_iter()` on a `ground()` handle | [Optimization](solving.md#optimization) |
| assumptions | `solve(assumptions=[...])` — on the program directly, or on a `ground()` handle when the same program answers many questions | [Ground once, solve many](solving.md#ground-once-solve-many) |
| `--mode=gringo --text` | `ground().ground_text()` | [Seeing the ground program](diagnostics.md#seeing-the-ground-program) |
| `--mode=gringo` (aspif) | `ground().aspif()` — byte-for-byte what clasp receives | [Seeing the ground program](diagnostics.md#seeing-the-ground-program) |
| `--time-limit` | `solve(timeout=)` / `optimize(timeout=)` | [The model stream](solving.md#the-model-stream) |
| `-t 4`, `--seed`, `--configuration=jumpy`, other clasp flags | `grounded.control.configuration`, set between `ground()` and the solve | [Solver options](escape-hatches.md#solver-options-and-the-raw-control) |

## Symbols in and out

Solutions come back as typed atoms, so most programs never touch a
`clingo.Symbol`. When you drive the clingo API directly — assumptions built
elsewhere, externals or observers through `grounded.control` —
`convert_predicate_to_symbol` and `convert_symbol_to_predicate` cross the
boundary in both directions, recursively, classical-negation sign included.
See [Clingo symbol interop](escape-hatches.md#clingo-symbol-interop).

## Receipts

The tables above are claims about what the library renders. These blocks are
the receipts: executed by the test suite in CI, so a spelling that drifts
breaks the build, not you. Every transcript below is the library's real
output. First, the pieces the receipts are built from:

```python
from aspalchemy import (
    ANY,
    ASPProgram,
    Choice,
    Compl,
    ConditionalLiteral,
    Count,
    Field,
    INF,
    Not,
    Number,
    Predicate,
    RangePool,
    SUP,
    V,
    pool,
)

X, Y = V.X, V.Y

class P(Predicate):
    x: Field[int]

class Q(Predicate):
    x: Field[int]
```

Terms and literals:

```python
>>> ANY.render()
'_'
>>> pool(range(1, 6)).render()
'1..5'
>>> pool([1, 3, 5]).render()
'(1; 3; 5)'
>>> X.in_(RangePool(1, 5)).render()
'X = 1..5'
>>> (X == Y + 1).render()  # equality binds X: safe
'X = Y + 1'
>>> SUP.render(), INF.render()
('#sup', '#inf')
>>> ConditionalLiteral(P(x=X), Q(x=X)).render()
'p(X) : q(X)'
```

Arithmetic spellings — Python operator in, clingo operator out:

```python
>>> (X // 2).render()
'X / 2'
>>> (X % 2).render()
'X \\ 2'
>>> (Number(1) | 2).render()
'1 ? 2'
>>> Compl(X).render()
'~X'
>>> abs(X).render()
'|X|'
```

Negation, in all four of its flavors:

```python
>>> Not(P(x=X)).render()
'not p(X)'
>>> (~~P(x=X)).render()  # preserved, not collapsed
'not not p(X)'
>>> (~(X != 3)).render()  # complement, not a "not" wrapper
'X = 3'
>>> (-P(x=3)).render()  # classical: the sign is on the atom
'-p(3)'
```

Choices, aggregate guards, and bare atoms:

```python
>>> Choice(P(x=X), condition=Q(x=X)).exactly(1).render()
'{ p(X) : q(X) } = 1'
>>> (Count(X, condition=P(x=X)) > 3).render()
'#count{ X : p(X) } > 3'
>>> (Count(X, condition=P(x=X)) >= 2).render()
'#count{ X : p(X) } >= 2'
>>> n = Predicate.define("n", [], show=False)  # a bare atom is a zero-arity predicate
>>> n().render()
'n'
```

And the full statement forms, through a program:

```python
program = ASPProgram()
width = program.define_constant("width", 9)
program.fact(P(x=width))
program.when(Q(x=X)).derive(P(x=X))
program.forbid(P(x=X), Q(x=X))
program.when(Q(x=X)).derive(Choice(P(x=X), condition=Q(x=X)).exactly(1))
```

```python
>>> print(program.render())
% Generated by aspalchemy ...
#const width = 9.
p(width).
p(X) :- q(X).
:- p(X), q(X).
{ p(X) : q(X) } = 1 :- q(X).

#show.
#show p/1.
#show q/1.
```

## Positioning

aspalchemy types the *program*: rules, choices, and constraints are validated
Python objects before clingo ever parses a line. clorm types the *data
boundary* — facts in, models out, with a relational query layer over
solutions — and by design leaves the rules themselves as ASP text. The two
tools solve different problems: if you want to keep writing rules in `.lp`
and query solutions relationally, clorm is the right tool; if you want the
program itself to be typed Python, you are in the right docs. Solution
handling here is deliberately minimal — typed atoms, loud failures
([Solving and Results](solving.md)) — and the two compose: aspalchemy to
define the program, clorm to handle the data.
