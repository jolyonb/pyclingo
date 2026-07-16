# TODO

This is a wishlist of items.

- **Read-path performance at scale: reconstruction is what remains, now
  profiled (2026-07-16).** The 1.4.1 round fixed the two hot spots —
  `render()` caches on the frozen instance (hashing 100k atoms into a set
  0.68s → 0.016s) and `AtomCollection.__contains__` answers from a
  lazily-built per-class set (one membership check at 100k atoms 1.25s →
  microseconds). Reconstruction was then profiled at 19.4 µs/atom
  (cell/3, 100k atoms; ~99% of first-model latency at that scale). Key
  finding: THE CHECKS ARE NEARLY FREE — skipping all validation buys only
  2.5% — the cost is machinery: the biggest item (~26%) is
  `Field._validated` round-tripping every int/str through the interning
  `Number()`/`String()` constructors purely to reuse their checks
  (throwaway objects, guaranteed cache misses); then descriptor/dataclass
  dispatch, clingo's cffi property reads (~3.7 µs, irreducible), the
  `__post_init__` depth walk, and a per-atom `dataclasses.fields()` call
  in the converter that `_field_names` exists to avoid. The adjudicated
  menu:
  - DONE in 1.4.2: (P1) converter uses positional construction with no
    per-atom `dataclasses.fields()` walk; (P2) `_validated` calls the
    shared validators (require_int32/require_clean_string) directly
    instead of building throwaway Numbers/Strings. Combined: ~19 →
    ~12.5 µs/atom.
  - HELD until 10^6-atom models are real: (P3) a checked fast-path
    constructor for solver-returned symbols (`object.__new__` + direct
    dict fill, ALL validation retained; 5.6 µs, first-model 1.94s → 0.63s).
    Design when taken: per-class `_fast_path_ok` stamped at class creation
    (a subclass with a user `__init__`/`__post_init__` falls back to the
    normal path), parity tests same-atom/same-errors on both paths,
    `_negated`/`_depth` set exactly as `__post_init__` does, never pre-set
    `_render_cache`. int32 range checks are skippable there (clingo
    numbers are int32 by representation).
  - REJECTED permanently: (P4) unvalidated construction — silently accepts
    raw_asp strings with quotes/backslashes and type-mismatched atoms, for
    2.5%. (Slots also rejected, same date: ~40 B/atom ceiling, zero read
    speedup on CPython 3.14, and dataclass(slots=True) returns a new class
    the __init_subclass__ creation path cannot swap in; columnar storage in
    AtomCollection is the 10^7-scale memory lever if ever needed.)
  - SET ASIDE: (P5) lazy materialization from stored Symbols — relocates
    read-back teaching errors from iteration time to first-access time,
    and P3 removes most of its motivation; composable with P3 later.
  Realistic floor: ~5–6 µs/atom fully validated. Keep any "fast at scale"
  claims scoped to what they mean (hidden atoms are never read back at
  all).

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
