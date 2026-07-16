# TODO

This is a wishlist of items.

- **Read-path performance at scale: reconstruction is what remains.** The
  1.4.1 round fixed the two hot spots — `render()` caches on the frozen
  instance (so render-based eq/hash stopped rebuilding strings: hashing
  100k atoms into a set 0.68s → 0.016s) and `AtomCollection.__contains__`
  answers from a lazily-built per-class set (one membership check at 100k
  atoms 1.25s → microseconds). What's left is construction: reconstruction
  builds a validated dataclass instance per atom, ~10 µs each (~1s per
  100k atoms) — profile it if 10^6-atom models become real. Slots were
  investigated and rejected (2026-07-16): ~40 B/atom ceiling, zero read
  speedup on CPython 3.14, and dataclass(slots=True) returns a new class,
  which the __init_subclass__ creation path cannot swap in; if atom memory
  ever matters at 10^7 scale, columnar storage in AtomCollection is the
  lever, not per-instance slots. Keep any "fast at scale" claims scoped to
  what they mean (hidden atoms are never read back at all).

- **Model two-sided aggregate guards internally.** A
  first-class banded form could also steer users away from the real trap,
  bind-then-compare (N == Count(...), N >= lo, N <= hi), which ships clasp one
  aggregate body per feasible N. Rejected once on design grounds: guards on
  Aggregate would make the type's legality position-dependent (a guarded
  aggregate cannot enter a Comparison). Needs a design that avoids that.

- **Multi-shot solving.** The big rock. clingo's incremental workflow —
  #program parts grounded onto one Control across successive solves, the
  iterative-deepening/planning idiom — is entirely unmodeled: we ground a
  single base part, and raw_asp() rejects #program outright. Supporting it
  is a genuine design project, not a feature bolt-on: it breaks
  GroundedProgram's core promise (an immutable snapshot that solves the same
  program forever) in favor of a handle that accretes state, and it needs
  answers for how segments map to parts, what part parameters look like in
  typed Python, and what the teaching errors become when statements land in
  never-grounded parts. Undecided and not a commitment: #external
  (multi-shot's usual companion for per-step toggles); ground()+assumptions
  already covers much of that use today, so external support should be
  argued from a concrete need, not completeness.

- **Separate fact/rule files.** It would be nice to be able to separate input
  data from the rules, rather than always rendering everything together.
