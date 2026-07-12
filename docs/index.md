# ASPAlchemy

<p class="site-hide"><em>&#128214; You are reading the docs source on GitHub &mdash; the rendered site lives at <a href="https://jolyonb.github.io/aspalchemy/">jolyonb.github.io/aspalchemy</a>.</em></p>

Describe the rules of your problem in Python — which states border which, which meetings clash, which seats must differ — and the solver finds every solution that satisfies them: timetables, seatings, puzzles. ASPAlchemy is a Python ORM for [clingo](https://potassco.org/clingo/): you author Answer Set Programming rules as typed Python objects, it renders them to ASP source, solves through the clingo API, and hands the answer sets — the solutions — back as typed Python values. And because your program is Python, it is *dynamic* — rules built with loops, functions, and real data reshape themselves around the input in ways a frozen `.lp` file never can.

Here is the whole of n-Queens — place eight queens so that none attacks another. The Python states the rules; the solver does the searching:

```python
from aspalchemy import (
    ASPProgram, Choice, Count, Field, Predicate, RangePool, Variable,
)

class Queen(Predicate, name="q"):
    row: Field[int]
    col: Field[int]

program = ASPProgram()
n = program.define_constant("n", 8)
R, C, D = Variable("R"), Variable("C"), Variable("D")
board = RangePool(1, n)

# every row and every column holds exactly one queen
program.when(R.in_(board)).choose(Choice(Queen(row=R, col=board)).exactly(1))
program.when(C.in_(board)).choose(Choice(Queen(row=board, col=C)).exactly(1))

# no two queens share a diagonal
falling, rising = RangePool(2, 2 * n), RangePool(1 - n, n - 1)
program.forbid(Count(C, Queen(row=D - C, col=C)) >= 2, D.in_(falling))
program.forbid(Count(C, Queen(row=D + C, col=C)) >= 2, D.in_(rising))

queens = program.solve().first().atoms(Queen)  # .row and .col are plain ints
assert len(queens) == 8
assert {q.row for q in queens} == {q.col for q in queens} == set(range(1, 9))
assert len({q.row - q.col for q in queens}) == 8  # all falling diagonals distinct
assert len({q.row + q.col for q in queens}) == 8  # all rising diagonals distinct
```

And `program.render()` hands back the classic encoding — the one you'd have written by hand:

```python
rendered = program.render()
assert "{ q(R, 1..n) } = 1 :- R = 1..n." in rendered
assert ":- #count{ C : q(D - C, C) } >= 2, D = 2..2 * n." in rendered
```

```text
#const n = 8.
{ q(R, 1..n) } = 1 :- R = 1..n.
{ q(1..n, C) } = 1 :- C = 1..n.
:- #count{ C : q(D - C, C) } >= 2, D = 2..2 * n.
:- #count{ C : q(D + C, C) } >= 2, D = 1 - n..n - 1.

#show.
#show q/2.
```

(The textbook writes the diagonal tests as body braces, `{ q(D-J,J) } >= 2`; aspalchemy [spells cardinality tests as Count comparisons](choices-and-aggregates.md#cardinality-tests-are-not-choices), which grounds to the same solver input.)

## Two ways in

- **New to ASP?** Start with [Your First Program](getting-started.md) — you'll be solving your own problem within the hour — then watch the same verbs handle a real 9×9 puzzle in [Walkthrough: Numberlink](numberlink.md).
- **Already write clingo?** [Clingo to ASPAlchemy](clingo-map.md) answers what's supported, what's spelled how, and what's deliberately refused — with the reasoning in [What We Don't Support](unsupported.md).

## Why ASPAlchemy

- **Your rules are Python objects.** Predicates are classes with typed fields;
  atoms are instances; rules are built from both. A misspelled field or a
  missing argument is a type error before clingo ever runs, and the pieces you
  use over and over live in ordinary variables — see
  [Predicates and Data](predicates.md).
- **The code reads as English.** `program.when(...).derive(...)`,
  `program.forbid(...)`, `Choice(...).exactly(1)` — the queens program above
  can be read aloud, roughly correctly, by someone who has never seen ASP.
  The verbs live in [Rules and Terms](rules.md).
- **You never need to see the clingo code.** The whole loop — express the
  rules, solve, consume typed answers — happens in Python; the generated ASP
  is one `render()` away whenever you want it.
- **It emits correct clingo.** Constructs clingo would reject — unsafe
  variables, malformed rules, syntax errors — are refused as you build them,
  at the Python line at fault; the few shapes only grounding can judge still
  fail loudly, mapped back to your source
  ([Diagnostics & Grounding](diagnostics.md)).
- **It's opinionated, with guardrails.** Constructs that are nearly always a
  mistake are refused, and every refusal says what you probably meant instead
  — the reasoning lives in [What We Don't Support](unsupported.md), and
  [`raw_asp()`](escape-hatches.md) accepts verbatim clingo when you genuinely
  need the full language.
- **Solutions are first-class.** Iterate models lazily, run brave/cautious
  consequence analyses, solve prioritized optimizations, and read atoms back
  as plain `int`s and `str`s — [Solving and Results](solving.md).

**"But the Python is longer than the `.lp`!"** It is — on a toy. Count again,
though: the *rules* are four statements in both versions, line for line; the
extra is the imports and the predicate declaration, a fixed cost that buys
typed fields, autocomplete, and the typed read-back the asserts above lean on.
The part that grows with a real problem is data — and data arrives as
`json.load(...)` or a database query, reshaped by ordinary Python, not as
facts retyped into a frozen file. That's the ORM trade, the same one
SQLAlchemy makes: a few declarations up front so that the hundredth rule is
as safe as the first.

## Install

```bash
pip install aspalchemy    # or: uv add aspalchemy
```

Requires Python 3.14+ — a deliberate, tinkerer-first choice: ASP is a small community, and we reached for the best available tools rather than the widest floor. clingo 5.8+ is installed automatically; releases live on [PyPI](https://pypi.org/project/aspalchemy/).

## These docs run

Every Python block on this site is executed top-to-bottom by the test suite in CI. When a page shows generated ASP or a solved model, an adjacent assert pins the claim — the examples cannot silently rot, and what you paste is what runs. The same culture holds below the docs: the library itself is gated at 100% line coverage, and claims about clingo's behavior are pinned by tests that run the real solver.

## More

- [Why not clorm?](clingo-map.md#positioning) — the boundary between the two tools, and how they compose.
- [aspuzzle](https://github.com/jolyonb/aspuzzle) — what this looks like at scale: a puzzle-solving framework built on ASPAlchemy.
- [Changelog](https://github.com/jolyonb/aspalchemy/blob/main/CHANGELOG.md) — what shipped, release by release.
