# Changelog

## 1.4.0 — 2026-07-15

### Breaking

- **The polymorphic Predicate field is now `Field[PredicateArg]`; `PredicateField` is
  gone.** Every field is now a `Field[...]`: the "holds anything" slot is
  spelled `Field[PredicateArg]`, where `PredicateArg` is the exported "any
  predicate argument" union. The old bare `x: PredicateField` no longer works —
  rewrite it as `x: Field[PredicateArg]`. (`PredicateField` is removed from the
  public API; `PredicateArg` replaces it.)

- **A polymorphic slot now reads back plain Python, not a wrapped term.**
  Reading a `Field[PredicateArg]` field by attribute used to hand back a
  `Number` or `String`, so callers wrote `atom.order.value` to reach the value.
  It now reads plain, exactly as a `Field[int]`/`Field[str]` slot always has —
  `atom.order` *is* the `int`. The `Number`/`String` term view has not gone
  anywhere; it lives on bracket access, which is unchanged:

  ```python
  atom.order          # 1        (was Number(1))
  atom["order"]       # Number(1) (unchanged — the Term view)
  ```

  Migration: drop the `.value` from attribute reads of polymorphic fields
  (`atom.order.value` → `atom.order`), or read `atom["order"].value` to keep
  the term. Typed `Field[...]` fields are unaffected — they already read plain.

- **A predicate's arguments are exactly its `Field[...]` slots; every other
  annotation is refused.** An annotation that is not a `Field[...]` and not a
  `ClassVar` now raises at class creation, naming the fix. This makes a
  forgotten `Field[...]` a loud error instead of a silent one: `age: int` — a
  bare, untyped field that used to work in 1.3.0 (reading back a wrapped term) —
  is refused with a pointer to `Field[int]`/`Field[PredicateArg]`, rather than
  silently changing arity or corrupting reads. Non-argument class data has two
  supported homes, both unaffected: a `ClassVar` for a typed constant, and a
  bare *unannotated* assignment for anything else. A `ClassVar` may not shadow a
  `Predicate` member, and a subclass may only *add* fields — re-declaring an
  inherited field is refused.

### Changed

- **The read model is now uniform, so `Field[...]` only tightens writes.**
  Every field — typed or `Field[PredicateArg]` — reads back as plain Python; a
  typed `Field[...]` annotation adds write-validation and a static ground type,
  and no longer changes what any read returns. Narrowing a `Field[PredicateArg]`
  slot to a typed one is a pure tightening with no read-site churn.

- **`Field[PredicateArg]` reads as the value union**
  (`int | str | Value | Predicate | Expression | Pool`, some narrowing), not
  `Any`; `Field[Any]` is refused, with a pointer back to `Field[PredicateArg]`.

- **Atoms now `repr()` as plain Python** — `Person(name='ada', age=3)`, not
  `Person(name=String('ada'), age=Number(3))`. The `Number`/`String` wrappers
  are internal; `repr` keeps them out. (`str()`/`canonical_str()` — the ASP
  forms — are unchanged.) `RangePool`/`ExplicitPool` also gained a
  reconstructable `repr` (`RangePool(1, 5)`, `ExplicitPool([1, 3, 5])`) instead
  of the default object address.

## 1.3.0 — 2026-07-14

### Breaking

- **A builder's mutator returns `None`; everything else returns a value.** Five
  methods used to mutate a builder *and* hand it back for chaining (`add()` on
  both builders, and `Choice`'s three bounds), so they read as values while
  behaving as statements. That is now resolved in both directions, and the rule
  is worth stating plainly: `add()` is the only thing that changes a builder,
  and it returns nothing. (Program-level verbs that mutate and return something
  you need — `define_constant()`, `add_segment()` — are unchanged: they hand
  back a different object, not themselves.)

- **`Choice.add()` and `Aggregate.add()` return `None`** rather than `self`,
  the same contract as `list.append`. Chained construction
  (`Choice(p).add(q).add(r)`) becomes a statement per element:

  ```python
  menu = Choice(p)
  menu.add(q)
  menu.add(r)
  ```

- **A `Choice`'s cardinality bounds no longer mutate it.** `exactly()`,
  `at_least()` and `at_most()` each return a NEW `Choice` carrying the bound,
  leaving the one they were called on untouched. So elements are built and
  bounds are values, and the two halves no longer contradict each other.

  The point is reuse: one menu of elements can be bounded several ways for
  several rules, which is the common shape of "the data decides how many".
  Bounding a *frozen* `Choice` is legal for the same reason: a captured choice
  is fenced against being rewritten, and bounding rewrites nothing. Freezing
  still fences `add()`, which is the operation that could silently change a
  recorded rule.

### Added

- **`require()` now accepts an atom, not only a comparison.** `require()` states
  what must hold and writes the constraint forbidding the opposite; that flip
  now covers predicates as well as comparisons — `require(p)` renders `:- not p`
  (p must hold), the positive spelling of `forbid(~p)`. A *negated* target is
  refused: `require(~p)` would flip to `not not p` (default negation on an atom
  is preserved, not cancelled), which is not `:- p`, so it points you at
  `forbid(p)` instead.

- **`Choice.copy()` and `Aggregate.copy()`**: an independent, *mutable* copy of
  a builder, with the same elements. This is the way out of a frozen builder —
  the copy is held by no rule, so building on it cannot rewrite anything already
  recorded, which is the only thing freezing ever protected. The freeze error
  now points at it, and the cardinality bounds are built on it.

- Copy semantics are now explicit, and the two kinds differ on purpose:
  `copy()` unfreezes, while `copy.copy()` and `copy.deepcopy()` are *faithful*
  (frozen stays frozen, receipt included). The dunders must be faithful because
  `ASPProgram.copy()` deep-copies a program and the copy's rules still hold
  their captured builders: unfreezing those would hand back a program whose
  recorded rules could be silently rewritten.

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
