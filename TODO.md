# TODO

This is a wishlist of items.

- **Read-path performance at scale.** The model-read path is tuned for
  puzzle-sized models, not industrial ones: `Predicate.__eq__`/`__hash__` go
  through `render()` (every set/dict operation on atoms builds strings),
  `AtomCollection.__contains__` is a linear scan over a per-class list with
  that render-based equality inside, and reconstruction builds a validated
  dataclass instance per atom. Fine at 10^4 atoms; will hurt at 10^5–10^6.
  Options when it matters: cache the rendered form on the atom, back
  membership with a set, profile reconstruction. Until then, keep any
  "fast at scale" claims scoped to what they mean (hidden atoms are never
  read back at all).

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
