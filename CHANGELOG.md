# Changelog

## 1.5.2 — 2026-07-21

### Changed

- **`fact()` accepts zero facts, as a no-op.** It used to raise
  `ValueError` on `fact()` with nothing to state. But `fact(*atoms)` over
  a generated collection is the ordinary spelling, and a generated
  collection is legitimately empty — the refusal only made every caller
  write the same guard around it, to reach the same outcome the no-op
  gives them. Stating nothing adds nothing; that is not an error worth
  raising.

## 1.5.1 — 2026-07-17

### Added

- **`GroundedProgram.grounding_time`: wall-clock seconds the ground()
  took.** Rendering, gringo's instantiation, and snapshot construction
  together. The search handles' statistics deliberately start their
  `wall_time` after grounding, so the phase that dominates large
  programs was recorded nowhere; now the grounding carries its own
  receipt.

## 1.5.0 — 2026-07-17

### Added

- **`ASPProgram.recursion_profile()` / `analyze_recursion()`: the recursive
  components of the predicate dependency graph, before any grounding is
  paid.** Gringo grounds each strongly connected component as
  one fixpoint, re-evaluating its rules across the iteration — so a
  statement inside a component that need not feed the recursion (a
  derivation restatable as a requirement) is the classic slow-grounding
  finding, and it is visible from program structure alone. Each
  `RecursiveComponent` carries the component's signatures, the statements
  grounding inside its fixpoint (with authoring locations), and an
  unstratified flag — the component's cycle passes through default
  negation, making the rules strongly circular: solving degrades to
  guess-and-check search, and it is almost always unintended. Components 
  are the strongly connected components of the FULL
  dependency graph (positive and negated edges together, the textbook
  object of stratification), so negation-only cycles and positive
  fixpoints entangled by mutual negation are reported and flagged, not
  silently ignored. Static analysis in a new `recursion` module;
  `raw_asp` text is ignored.

- **`GroundedProgram.statement_profile()` / `analyze_statements()`: where the
  grounding's WORK comes from, per statement.** `grounding_profile()` counts
  the atoms each signature ends up with, which leaves a documented blind
  spot: constraints have no head to charge, and a wide-bodied rule feeding a
  small head hides under the head's count. The statement profile closes it —
  every statement charges its own row, ranked by ground instantiation count
  and joined to its authoring line.

  How it counts: an instrumented re-ground tallies a reserved marker
  literal per statement with a ground-program observer, with the instrumentation chosen per
  statement kind — classified structurally from the render's element
  column — so the copy grounds as faithfully as possible. Facts stay REAL
  facts, counted by a companion rule whose pool expansion instantiates
  once per fact instance, so aggregates over facts evaluate exactly as
  the true grounding; aggregates over atoms DERIVED
  from facts remain an upper bound, stated in the docs. Weak constraints are
  not touched at all: their priority is redirected to a reserved value
  and the minimize callback's per-tuple entries are counted there.
  Anonymous variables are renamed apart so gringo's projection rewrite
  cannot hide a statement's join work — except under default negation,
  where renaming would be unsafe. minimize()/maximize()
  directives are the one excluded statement kind. Only `raw_asp` text
  takes a line-based pass: statements spanning several lines or sharing
  one line pass through uncounted. Each call pays a full in-process
  re-ground with `ground_text()`'s stateful-context caveat but no
  threading caveat. `StatementGrounding` is exported alongside
  `SignatureGrounding`.

## 1.4.3 — 2026-07-17

### Fixed

- **Abandoning an async search no longer deadlocks the interpreter at
  exit.** The abandoned-search family's third door, and this one HANGS
  instead of crashing: a solve with a `timeout` engages clasp's native
  solve thread (async solving), and a search abandoned to interpreter
  shutdown wedged the exit — the solve thread must attach to Python to
  finish (the on_finish callback), CPython parks threads attaching during
  finalization, and freeing the Control waits on that very thread forever
  (deterministic: 10 hangs in 10 runs, timeout-bearing solves only). The
  1.2.0/1.4.2 skip guards cannot close this door — the wait is inside
  clingo's own `Control.__del__`, and running cancel/get instead would
  wait on the same never-finishing thread — so the fix acts EARLIER: an
  atexit hook (registered at import, so it runs after later-registered
  caller hooks) closes every async search still open while the solve
  thread can still attach, where cancel and the statistics snapshot both
  work and the exit stays an exit. Sync searches have no second thread
  and are untouched; the skip guards still cover their shutdown and
  GC-cycle doors.

## 1.4.2 — 2026-07-16

### Performance

- **Solution-atom reconstruction dropped its per-atom bookkeeping.** The
  converter called `dataclasses.fields()` for every atom read back from a
  model and built a keyword dict to construct it; it now uses the cached
  field order and constructs positionally (the name/arity lookup already
  proves the argument count). Roughly a 10% cut in per-atom reconstruction
  cost; teaching errors for unreadable atoms are unchanged.

- **Field writes validate directly instead of round-tripping through the
  interned wrappers.** Writing an int or str into a field — every argument
  of every reconstructed solution atom, and every `fact()` argument — built
  a throwaway `Number`/`String` purely to reuse its validation, a
  guaranteed interning-cache miss per write. The range and content rules
  now live in shared validators that `Number`, `String`, and the Field
  write path all call, so nothing is enforced in two places. Combined with
  the converter cut above, reconstruction measured ~19 → ~12.5 µs/atom
  (100k three-int-field atoms); program-side writes speed up the same way.
  A bonus for diagnostics: out-of-range and bad-content errors now name
  the field (`Field 'age' value ... outside clingo's integer range`)
  instead of the internal wrapper.

### Fixed

- **A reference cycle in caller code capturing an abandoned search no longer
  risks a segfault.** The 1.2.0 fix covered interpreter shutdown, but the
  same crash had a second door: a caller-side cycle holding a grounding with
  a suspended search makes grounding, handle, generator, and Control garbage
  *together*, and cycle collection runs finalizers over a garbage set in
  undefined order — so `Control.__del__` could free the native object before
  `GeneratorExit` reached the generator, whose cleanup then called native
  clingo on freed memory (deterministically reproducible; SIGSEGV with no
  traceback, mid-run, nowhere near the code at fault). Every native teardown
  call — cancel/get/core, the handle close, the statistics snapshot — is now
  guarded by a single finalization check; `gc.is_finalized` answers the
  ordering question exactly, so a normal refcount teardown still records
  statistics as before, and a GC-initiated one skips what nobody could
  observe anyway.

### Breaking

- **Querying a result for a predicate class the program never declared now
  raises a teaching error instead of answering a quiet `[]`/`False`.** The
  house rule has always been that an empty answer which reads as "none were
  derived" must never be a lie — hidden classes, class-instead-of-atom
  probes, and `#const`-bearing atoms already raised — but a class that was
  never part of the program at all still answered quietly. That silence hid
  the commonest mix-up: querying a base class when the program was built
  with its `in_namespace()` clone (or the reverse) — lookup is by exact
  class, so the answer was always empty no matter what was derived. Both
  `atoms(Cls)` and `atom in collection` now raise for never-declared
  classes, naming the declared relative when there is one. The honest
  empties are untouched: a *declared* class with no derived atoms still
  answers `[]`, and a hand-built `AtomCollection` (which carries no program
  knowledge) stays permissive.

## 1.4.1 — 2026-07-16

### Performance

- **Atom equality, hashing, and membership no longer re-render on every
  comparison.** An atom's rendered form is its canonical identity (`==` and
  `hash()` compare it), and it was recomputed from the term tree on every
  call — so set/dict workloads over large models paid a full re-render per
  operation, and one `atom in collection` check at 100k atoms took over a
  second. `render()` now computes once and caches on the frozen instance
  (lazily — atoms that are only field-read pay nothing), and
  `AtomCollection` membership answers from a per-class set built on the
  first `in` query instead of scanning a list. Measured at 100k atoms:
  hashing the model into a set 0.68s → 0.016s; a single membership check
  1.25s → microseconds. Construction and plain field reads are unchanged.

### Fixed

- **A right operand at the multiplicative level always keeps its
  parentheses; regrouping there could silently change the computed value.**
  The renderer parenthesized a division/modulo child under `*` only when the
  child *itself* was `/` or `\`, so a `*` child on the right of a `*` parent
  rendered bare — and any division on that child's left spine was regrouped
  by gringo's left-associative parse: `5 * ((7 / 3) * 2)` (which is 20)
  rendered as `5 * 7 / 3 * 2` (which is 22). Integer division truncates, so
  the regrouping is not value-preserving. The direct spelling had rendered
  this way since 1.0.0; 1.4.0's involution collapse widened the exposure by
  also stripping the protective parentheses from `a * -(-(b // c * d))` and
  the `Compl(Compl(...))` equivalent, which had rendered correctly before.
  Right-grouped trees at the multiplicative level now always render their
  parentheses (`5 * (7 / 3 * 2)`), left-nested chains stay minimal, and the
  differential fuzz suite now generates division and modulo nodes (with
  operands constrained to where clingo and Python agree), so it would catch
  this whole class.

- **Name collisions between subclass class data and inherited fields are now
  refused at class creation.** Three spellings used to slip past the
  re-declaration guard and corrupt the schema silently: a `ClassVar`
  re-annotating an inherited field made `dataclass()` silently *delete* that
  field from the signature (wrong arity, wrong render, the constant
  masquerading as field data); a bare assignment (or `def`) reusing an
  inherited field's name shadowed the base's `Field` descriptor, so every
  write to that field skipped validation entirely; and a new subclass
  `Field[...]` named after an inherited `ClassVar`/attribute made
  `dataclass()` read the base's value as a silent default nobody wrote. All
  three now raise a teaching `TypeError` at class creation. Explicit field
  defaults assigned in the subclass's own body remain legal and are now
  pinned by tests: a default fills in when omitted, an explicit value
  overrides it, and both routes pass the same per-field write validation.

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
