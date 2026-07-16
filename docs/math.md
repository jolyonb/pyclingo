# Arithmetic

*How Python operators become ASP arithmetic, and where the two languages
disagree about what numbers mean.*

Expressions here appear in rules through [comparisons](statements.md#comparisons);
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
| `-x` | `-x` | doubled, it cancels; see doubled unary operators below |
| `Compl(x)` | `~x` | bitwise complement — `~` itself is reserved for default negation; doubled, it cancels |
| `abs(x)` | `\|x\|` | doubled, it collapses to one `\|x\|` |

## Precedence

Gringo's precedence, established empirically (loosest to tightest): `^`,
then `?`, then `&`, then `+ -`, then `* / \`, then `**` (right-associative),
then unary `-` and complement. Two traps for Python intuitions: the bitwise
operators bind *looser* than `+`, and unary minus binds *tighter* than `**`
(in gringo `-2**2` is `(-2)**2 = 4`; in Python it is `-(2**2) = -4`).

You do not need that table to read ASPAlchemy's output. Python builds the
expression tree using Python's precedence, and the renderer guarantees
clingo evaluates that same tree: classic arithmetic renders with minimal
parentheses, while anything involving `**` or the bitwise operators is
deliberately over-parenthesized (power even against itself, making its
associativity explicit). Two tidies are applied to the tree itself, both
cosmetic and value-preserving: the [negative-operand
fold](#negative-operands) and the [collapse of doubled unary
operators](#doubled-unary-operators) below.

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
hand: `X + -1` is spelled `X - 1`, and a subtracted negative turns into an
addition. (Both spellings are legal ASP — gringo parses a bare negative
literal as a unit in every operator slot — so this is cosmetic, and
value-preserving.)

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
>>> (X - (-Y)).render()
'X + Y'
>>> (X * Number(-1)).render()  # only + and - have a sign to absorb
'X * -1'
```

The fold happens at construction, like [`Not()` on a plain
comparison](statements.md#default-negation), so it is visible in the tree you get
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

## Doubled unary operators

Unary minus and complement are *involutions* in clingo's arithmetic: `-(-t)`
is `t` and `~(~t)` is `t`, for every term `t`. So a doubled one is dropped
when the expression is built, and what you get back is the inner term itself
— not an expression wrapping it. `abs` is *idempotent* rather than an
involution, so it keeps one node and drops the other. (Probed against clingo
5.8: `||t||` does parse in gringo and means `|t|`, so the doubled form was
ugly rather than broken; all three collapses preserve the value.)

```python
from aspalchemy import Compl
```

```python
>>> (-(-X)).render()
'X'
>>> (-(-X)) is X            # the node is gone, not merely hidden
True
>>> Compl(Compl(X)).render()
'X'
>>> abs(abs(X)).render()
'|X|'
>>> (-(-(-X))).render()     # every doubled pair goes, however deep the stack
'-X'
>>> (Y * (-(-X))).render()  # under every parent, not just + and -
'Y * X'
```

Unlike the [additive fold](#negative-operands), this has no exception at the
int32 floor. That fold refuses `Number(-2147483648)` because *2147483648* is
not a representable clingo integer — but clingo's unary minus wraps modulo
2^32 (probed against clingo 5.8: `-(-2147483648)` evaluates to
`-2147483648`), which is exactly what makes it an involution on every term
without exception. So the collapse is value-preserving at the floor too, and
fires there.

```python
>>> (-(-Number(-2147483648))) is Number(-2147483648)
True
>>> (X + Number(-2147483648)).render()  # while the fold still leaves this one alone
'X + -2147483648'
```

Because a doubled unary hands back the inner term, `-x` and `Compl(x)` no
longer always return an `Expression`: `-(-X)` *is* the `Variable` `X`. Both are
typed `Value | Expression`, so annotate what you accept as a term rather than
as an `Expression`. `abs()` is unaffected — it keeps its node, so it always
returns an `Expression`. The same is true of building an `Expression` by hand:
a type checker can only tell you what a unary construction returns when it can
see *which* operator you passed, so `Expression(None, op, x)` with a computed
`op` no longer type-checks. Build terms with the operators, not the
constructor.

The contrast to keep in mind is [default negation](statements.md#default-negation):
`not not p` is *preserved*, because default negation is not an involution on
literals — under stable-model semantics `not not p` is a genuinely different
literal from `p`. What collapses here is arithmetic on *terms*, where the
identity holds for every value.

## Where clingo and Python disagree

These are semantic differences in the *evaluation* of integer arithmetic.
ASPAlchemy hands clingo the expression tree you built (modulo the two cosmetic
normalizations above); clingo then evaluates it by clingo's rules, which differ
from Python's in four places:

1. **Integer division and modulo round differently on negatives.** Python
   floors: `-7 // 2 == -4` and `-7 % 2 == 1`. Clingo truncates toward zero:
   `-7/2 == -3` and `-7\2 == -1`. On non-negative operands they agree.

2. **Negative exponents.** Python's `2 ** -1` is `0.5` — a float, a type
   neither clingo nor ASPAlchemy has. Clingo evaluates `2**(-1)` to `0`.

3. **Clingo integers silently wrap at 32 bits.** `100000 * 100000`
   evaluates to `1410065408` (that is 10^10 mod 2^32) and `2**40` to `0`,
   with no warning of any kind. Python integers never overflow. If your
   puzzle arithmetic can exceed ±2^31, clingo will compute confidently
   wrong answers.

4. **Division by zero deletes the ground instance.** Raw clingo drops any
   rule instance whose arithmetic is undefined, emitting only an info-level
   message. ASPAlchemy's default `stop_on_log_level=INFO` promotes that to a
   GroundingError, so a division by zero fails loudly instead of silently
   shrinking your program. See
   [Clingo's messages](diagnostics.md#clingos-messages).

The good news: bitwise operations agree with Python exactly, negatives
included — clingo implements the same infinite-precision two's-complement
semantics (`-5 & 3 == 3`, `~(-6) == 5`).
