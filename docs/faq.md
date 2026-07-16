# FAQ

While nobody has actually ever asked these questions, we hope that they might be useful
to someone, or at least interesting...

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
gringo's actual evaluation, every refusal
encodes what *this* grounder accepts or silently misreads, and the empirical
claims are probed against the exact statement stream clasp receives.

## Can I render to the clingo AST directly?

No. Text is the interface, but it's not a limitation: clingo parses its
own language natively, so `program.render()` followed by clingo reading the
text does everything an AST bridge would (it is exactly what
[`ground()`](solving.md#ground-once-solve-many) does internally). If you're
driving the clingo API yourself, add the rendered text to your `Control`, and
cross the atom boundary in both directions with the
[symbol interop helpers](escape-hatches.md#clingo-symbol-interop).

## Can I keep using my existing `.lp` files?

Yes — as text. Read the file with ordinary Python and pass its contents to
[`raw_asp()`](escape-hatches.md), declaring the predicates it produces via
`predicates=` so its atoms round-trip typed. Or — might we suggest —
translate your files to Python with ASPAlchemy instead?
[Claude](https://claude.ai) is very good at exactly that...

## What about multi-shot solving and `#external`?

We lack support for both. `ground()` once plus per-solve assumptions
covers most incremental workflows; true multi-shot needs genuine design work
and is on the wishlist, and `#external` is deliberately undecided. The full
story: [Multi-shot solving](unsupported.md#multi-shot-solving-a-future-design-project).

## How large a problem can ASPAlchemy handle?

clingo will always be the bottleneck long before ASPAlchemy is. The
programs you write stay small, so the only place ASPAlchemy could itself
slow you down is moving data across the boundary — and even stating
millions of facts and reading millions of atoms back out of a solution
happens in seconds. If you genuinely have that much data, one nice split
is to let ASPAlchemy define the program and render the `.lp` files, then
hand the data boundary to clorm — which types exactly that, facts in and
models out.

## Why "ASPAlchemy"?

An homage to SQLAlchemy, and a claim to the same trade: the generated
language becomes an implementation detail while the program becomes typed
objects — what SQLAlchemy did for SQL, done for ASP.

## I have a request / found a bug!

Open an issue at
[github.com/jolyonb/aspalchemy](https://github.com/jolyonb/aspalchemy/issues).
As far as we're concerned, a confusing error message *is* a bug: every refusal is
supposed to teach the fix, so if one left you stuck, please report the
message that failed you.
