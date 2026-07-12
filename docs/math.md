# Arithmetic

*How Python operators become ASP arithmetic, and where the two languages
disagree about what numbers mean.*

Expressions here appear in rules through [comparisons](rules.md#comparisons);
for the operator-by-operator clingo spelling, see the
[translation map](clingo-map.md#arithmetic).

Everything here is pinned by executable
tests: the renderings below run as part of the test suite, and
`tests/aspalchemy/test_arithmetic.py` verifies each construct against clingo's
actual evaluation.

## Operator table

| Python | ASP rendering | Notes |
|--------|---------------|-------|
| `x + y` | `x + y` | |
| `x - y` | `x - y` | |
| `x * y` | `x * y` | |
| `x // y` | `x / y` | integer division; see sign quirk below |
| `x % y` | `x \ y` | modulo; see sign quirk below |
| `x ** y` | `x ** y` | right-associative in ASP |
| `x & y` | `x & y` | bitwise and |
| `x \| y` | `x ? y` | bitwise or — ASP spells it `?` |
| `x ^ y` | `x ^ y` | bitwise xor |
| `-x` | `-x` | |
| `Compl(x)` | `~x` | bitwise complement — `~` itself is reserved for default negation |
| `abs(x)` | `\|x\|` | |

## Precedence

Gringo's precedence, established empirically (loosest to tightest): `^`,
then `?`, then `&`, then `+ -`, then `* / \`, then `**` (right-associative),
then unary `-` and complement. Two traps for Python intuitions: the bitwise
operators bind *looser* than `+`, and unary minus binds *tighter* than `**`
(in gringo `-2**2` is `(-2)**2 = 4`; in Python it is `-(2**2) = -4`).

You do not need that table to read aspalchemy's output. Python builds the
expression tree using Python's precedence, and the renderer guarantees
clingo sees that same tree: classic arithmetic renders with minimal
parentheses, while anything involving `**` or the bitwise operators is
deliberately over-parenthesized (power even against itself, making its
associativity explicit).

```python
from aspalchemy import Number

a, b, c = Number(1), Number(2), Number(3)

# Classic arithmetic: minimal parentheses
assert (a + b * c).render() == "1 + 2 * 3"
assert (a - (b - c)).render() == "1 - (2 - 3)"

# Power and bitwise: explicit parentheses, always
assert (a + b**c).render() == "1 + (2 ** 3)"
assert (a**b**c).render() == "1 ** (2 ** 3)"
assert ((a & b) | c).render() == "(1 & 2) ? 3"

# Python parses -2**2 as -(2**2); the rendering preserves that tree
assert (-(b**b)).render() == "-(2 ** 2)"
```

## Where clingo and Python disagree

These are semantic differences in the *evaluation* of integer arithmetic.
aspalchemy renders your expression tree faithfully; clingo then evaluates it
by clingo's rules, which differ from Python's in four places:

1. **Integer division and modulo round differently on negatives.** Python
   floors: `-7 // 2 == -4` and `-7 % 2 == 1`. Clingo truncates toward zero:
   `-7/2 == -3` and `-7\2 == -1`. On non-negative operands they agree.

2. **Negative exponents.** Python's `2 ** -1` is `0.5` — a float, a type
   neither clingo nor aspalchemy has. Clingo evaluates `2**(-1)` to `0`.

3. **Clingo integers silently wrap at 32 bits.** `100000 * 100000`
   evaluates to `1410065408` (that is 10^10 mod 2^32) and `2**40` to `0`,
   with no warning of any kind. Python integers never overflow. If your
   puzzle arithmetic can exceed ±2^31, clingo will compute confidently
   wrong answers.

4. **Division by zero deletes the ground instance.** Raw clingo drops any
   rule instance whose arithmetic is undefined, emitting only an info-level
   message. aspalchemy's default `stop_on_log_level=INFO` promotes that to a
   GroundingError, so a division by zero fails loudly instead of silently
   shrinking your program. See
   [Clingo's messages](diagnostics.md#clingos-messages).

The good news: bitwise operations agree with Python exactly, negatives
included — clingo implements the same infinite-precision two's-complement
semantics (`-5 & 3 == 3`, `~(-6) == 5`).
