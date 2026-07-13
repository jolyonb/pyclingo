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
| `x + y` | `x + y` | a negative `y` folds into `-`; see negative operands below |
| `x - y` | `x - y` | a negative `y` folds into `+`; see negative operands below |
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
clingo evaluates that same tree: classic arithmetic renders with minimal
parentheses, while anything involving `**` or the bitwise operators is
deliberately over-parenthesized (power even against itself, making its
associativity explicit). The one tidy applied to the tree itself is the
cosmetic, value-preserving fold below.

```python
from aspalchemy import Number

a, b, c = Number(1), Number(2), Number(3)
```

```python
>>> (a + b * c).render()  # classic arithmetic: minimal parentheses
'1 + 2 * 3'
>>> (a - (b - c)).render()
'1 - (2 - 3)'
>>> (a + b**c).render()  # power and bitwise: explicit parentheses, always
'1 + (2 ** 3)'
>>> (a**b**c).render()
'1 ** (2 ** 3)'
>>> ((a & b) | c).render()
'(1 & 2) ? 3'
>>> (-(b**b)).render()  # Python parses -2**2 as -(2**2); the tree survives
'-(2 ** 2)'
```

## Negative operands

A negative right operand of `+` or `-` is folded into the operator when the
expression is built, so the rendering reads the way you would write it by
hand: `X + -1` is spelled `X - 1`, and a double negative cancels. (Both
spellings are legal ASP — gringo parses a bare negative literal as a unit in
every operator slot — so this is cosmetic, and value-preserving.)

```python
from aspalchemy import Variable

X, Y = Variable("X"), Variable("Y")
```

```python
>>> (X + Number(-1)).render()
'X - 1'
>>> (X - Number(-1)).render()
'X + 1'
>>> (X + (-Y)).render()
'X - Y'
>>> (X - (-(-Y))).render()
'X - Y'
>>> (X * Number(-1)).render()  # only + and - have a sign to absorb
'X * -1'
```

The fold happens at construction, like [`Not()` on a plain
comparison](rules.md#default-negation), so it is visible in the tree you get
back: an expression built as an addition of a negative reports `SUBTRACT`, and
holds the positive term.

```python
>>> from aspalchemy import Operation
>>> (X + Number(-1)).operator is Operation.SUBTRACT
True
>>> (X + Number(-1)).second_term
Number(1)
```

Exactly one value does not fold: the int32 floor, whose negation (2147483648)
is not a representable clingo integer, so there is no positive term to fold it
into. It is left as written, and is valid ASP as written.

```python
>>> (X + Number(-2147483648)).render()
'X + -2147483648'
>>> (X + Number(-2147483647)).render()  # its neighbour folds as usual
'X - 2147483647'
```

## Where clingo and Python disagree

These are semantic differences in the *evaluation* of integer arithmetic.
aspalchemy hands clingo the expression tree you built (modulo the cosmetic fold
above); clingo then evaluates it by clingo's rules, which differ from Python's
in four places:

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
