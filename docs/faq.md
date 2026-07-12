# FAQ

*Short answers, with links to the long ones.*

## Why not clorm?

Different jobs. [clorm](https://github.com/potassco/clorm) types the *data
boundary* — facts in, models out, with a relational query layer over
solutions — and by design leaves the rules themselves as ASP text. ASPAlchemy
types the *program*: the rules are validated Python objects. The full
comparison, including how the two tools compose, is in
[Positioning](clingo-map.md#positioning).

## Will you support ASP engines other than clingo?

No — and not out of neglect. The library's value is precisely that its
validation is hyper-specific to clingo: the safety analysis models gringo's
binding rules, the [arithmetic semantics](math.md) are pinned against
gringo's actual evaluation (32-bit wraparound included), every refusal
encodes what *this* grounder accepts or silently misreads, and the empirical
claims are probed against the exact statement stream clasp receives. A second
engine wouldn't dilute those guarantees — it would falsify them.

## Can I render to the clingo AST directly?

No — text is the interface, and that's not a limitation: clingo parses its
own language natively, so `program.render()` followed by clingo reading the
text does everything an AST bridge would (it is exactly what
[`ground()`](solving.md#ground-once-solve-many) does internally). If you're
driving the clingo API yourself, add the rendered text to your `Control`, and
cross the atom boundary in both directions with the
[symbol interop helpers](escape-hatches.md#clingo-symbol-interop).

## Can I keep using my existing `.lp` files?

Yes — as text. Read the file with ordinary Python and pass its contents to
[`raw_asp()`](escape-hatches.md), declaring the predicates it produces via
`predicates=` so its atoms round-trip typed. (`#include` is refused inside
raw blocks: you're in Python — use Python to read files.)

## What about multi-shot solving and `#external`?

Unmodeled today, honestly so. `ground()` once plus per-solve assumptions
covers most incremental workflows; true multi-shot needs genuine design work
and is on the wishlist, and `#external` is deliberately undecided. The full
story: [Multi-shot solving](unsupported.md#multi-shot-solving-a-future-design-project).

## Why Python 3.14+?

A deliberate, tinkerer-first choice. ASP is a small community and most users
start by exploring, not by deploying into a version-pinned production
environment — so the library reaches for the best available tools instead of
the widest floor. The modern type system does real work here: typed fields,
the dataclass transform behind predicate classes, and the annotations your
IDE completes against all lean on it.

## How large a problem can it handle?

Grounding and solving are clingo's own, so that part scales exactly as
clingo does. ASPAlchemy's additions sit at the boundaries — rule validation
at build time, typed read-back at solve time — and the read path is tuned
for puzzle-scale models rather than industrial ones;
[A note on scale](solving.md#a-note-on-scale) has the honest numbers and the
knobs that matter (chiefly: [hide](predicates.md) what you don't need to
read back).

## Why "ASPAlchemy"?

An homage to SQLAlchemy, and a claim to the same trade: the generated
language becomes an implementation detail while the program becomes typed
objects — what SQLAlchemy did for SQL, done for ASP. The transmutation
imagery comes free.

## I have a request / found a bug!

Open an issue at
[github.com/jolyonb/aspalchemy](https://github.com/jolyonb/aspalchemy/issues).
And by house policy, a confusing error message *is* a bug: every refusal is
supposed to teach the fix, so if one left you stuck, please report the
message that failed you.
