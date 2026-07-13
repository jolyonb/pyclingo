# Changelog

## 1.2.0 — 2026-07-13

- `ASPProgram.copy()` and `Segment.copy()` return an independent copy:
  statements, segments, constants and show settings added to either one
  afterwards do not appear in the other. The motivating use is a variant —
  solve a program, then copy it and push the copy somewhere the original must
  not follow (an extra fact, a tighter constraint, a what-if). `Segment.copy()`
  takes an optional `name`, because a segment's name is its key in a program:
  a copy destined for the same program needs a new one.
- Nothing mutable is shared by a copy. Values and atoms are exempt from the
  copying but not from the guarantee — immutable and interned, they hand
  themselves back rather than duplicate; a `Choice` or `Aggregate` already
  captured by a rule is frozen, and a frozen builder is a value; and predicate
  classes are classes, so the copy's show settings stay keyed by the very
  classes you declared. Groundings are not copied — a `GroundedProgram` is
  already an immutable snapshot, unaffected by later mutation of either
  program.
- Copying across an unfinished `when()` is refused, with an error naming the
  line the `when()` was opened on. A `when()` holds the segment it will write
  to, so no copy of it is the answer the caller means: the handle they hold
  belongs to the original. Likewise, a `Segment` handle kept from
  `add_segment()` still writes to the program it was added to — the copy holds
  its own segment of that name, reached with `duplicate["name"]`.
- **Abandoning a search no longer risks a segfault at exit.** A `SolveResult`
  that was never exhausted and never closed is finalized by the garbage
  collector during interpreter shutdown, by which time clingo's module state
  may already be gone — and the generator's cleanup read native statistics off
  the freed `Control`, crashing the process with no traceback (roughly two runs
  in three, on a program as small as two facts). The cleanup now skips the
  statistics snapshot while the interpreter is finalizing, where nothing could
  read it anyway. Taking one model and walking away — `next(iter(result))` — is
  a documented idiom, so it has to be safe, not merely discouraged.
- **`copy.deepcopy` of a `GroundedProgram` no longer duplicates clingo's
  `Control`.** It now hands the snapshot back, which is what a grounding
  already claims to be: immutable, and solvable many times. Duplicating it put
  two Python objects in front of one C object that only one of them owned,
  which failed either loudly (a cffi handle cannot be pickled) or, worse,
  quietly — a dangling handle that segfaulted at teardown. This is what made
  deepcopy safe on anything *holding* a grounding, such as an `ASPProgram`
  subclass that memoizes one, which is how the crash reached code that never
  copied a grounding on purpose.

## 1.1.0 — 2026-07-13

- Expressions now fold a negative right operand of `+` or `-` into the
  operator when they are built: `X + -1` renders as `X - 1`, `X - -1` as
  `X + 1`, and a negated term cancels the same way (`X - (-Y)` renders as
  `X + Y`). Both spellings were always valid ASP, so this is cosmetic and
  value-preserving — generated output now reads the way you would write it by
  hand. Like `Not()` on a plain comparison, the normalization is
  performed at construction and is therefore visible: an expression built as
  an addition of a negative reports `SUBTRACT`. The one value that does not
  fold is the int32 floor, whose negation is not a legal clingo integer.
- A doubled unary operator now collapses when the expression is built, in
  every position rather than only under a `+`/`-` parent: `-(-X)` IS `X`
  (the term itself, not an expression wrapping it), `Compl(Compl(X))` IS `X`,
  and `abs(abs(X))` renders `|X|`. Unary minus and complement are involutions
  in clingo's arithmetic and `abs` is idempotent, so this is cosmetic and
  value-preserving — with no int32 exception this time, since clingo's unary
  minus wraps modulo 2^32. `not not p` is unaffected: default negation is not
  an involution on literals, and stays preserved. Consequences worth knowing:
  `-x` and `Compl(x)` are now typed `Value | Expression` (a doubled one hands
  the inner term back), and a raw `Expression(...)` call whose `Operation` is
  not statically known no longer type-checks.

## 1.0.3 — 2026-07-13

Documentation release — no library changes.

- The readme (and the documentation site) now demonstrate what the library is
  actually *for*: a worked example where Python chooses both the predicate
  schema and the rules at runtime, so the same call emits a rectangular grid's
  adjacency rules or a hex grid's. Previously this was claimed but never shown.
- Documentation examples are now verified transcripts: the output a page
  displays — generated ASP included — is checked against the real thing on
  every commit, and teaching errors are shown as real tracebacks.

## 1.0.2 — 2026-07-12

Documentation and packaging release — no library changes.

- A complete documentation site at
  [jolyonb.github.io/aspalchemy](https://jolyonb.github.io/aspalchemy/):
  a tutorial and a worked Numberlink walkthrough for newcomers to ASP; a
  guide covering predicates, rules, choices and aggregates, solving, and
  diagnostics; and, for clingo users, a construct-by-construct translation
  map, an account of what the library deliberately refuses and why, and the
  escape hatches for when you need the full language. Plus an FAQ and a
  curated API reference.
- PyPI metadata: project links, classifiers, and search keywords.

## 1.0.1 — 2026-07-11

Documentation and packaging release — no library changes.

- New PyPI readme (now the repository root README): a worked map-coloring
  example executed by the test suite, the "Why ASPAlchemy?" story, and
  positioning relative to clorm
- Documentation published to
  [jolyonb.github.io/aspalchemy](https://jolyonb.github.io/aspalchemy/) via
  GitHub Pages, with a shared navigation header
- Release automation: CI runs the full quality gauntlet on pushes and pull
  requests; version tags publish to PyPI via Trusted Publishing

## 1.0.0 — 2026-07-11

Initial public release.

`aspalchemy` is a Python ORM for clingo: constraints are expressed as typed
Python objects, rendered to ASP source, solved via the clingo API, and
reconstructed back into typed Python values. Highlights:

- Full term hierarchy: variables, constants, predicates, pools, expressions,
  comparisons, aggregates, choices, conditional literals, negation (default
  and classical), and optimization directives
- Typed predicate fields with validation on write and plain-Python reads on
  solution atoms
- Solving surface: model iteration, brave/cautious consequences with
  refinement iterators, timeouts, and clingo-style statistics
- Source-location stamping: diagnostics name the Python line that authored
  the offending ASP statement
- Ground-program inspection via `ground_text()` and `aspif()`
- 100% test line coverage
