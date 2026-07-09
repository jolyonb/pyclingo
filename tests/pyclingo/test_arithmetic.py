"""
Arithmetic rendering pinned against clingo's actual evaluation.

Each case builds an expression tree twice from one lambda: once over pyclingo
Numbers (rendered into a fact and evaluated by clingo) and once over plain
Python ints. If the rendered parenthesization misrepresents the tree, clingo
computes a different value and the case fails. This pins gringo's precedence
and associativity facts empirically: ** is right-associative, unary minus
binds tighter than ** (unlike Python), mod shares the multiplicative level,
and the bitwise trio sits below additive (xor loosest, then or, then and).

Python-side note: the lambdas are parsed by PYTHON's precedence, which differs
from gringo's for ** and the bitwise trio. That is irrelevant here — both
evaluations share the one tree Python built, and the renderer's job is to
make clingo see that same tree.
"""

from collections.abc import Callable
from typing import Any

import pytest

from pyclingo import Abs, ASPProgram, Compl, Number, Predicate, Variable


def compl(x: Any) -> Any:
    """Bitwise complement for the dual-use case table: ~ on ints, Compl on terms."""
    return ~x if isinstance(x, int) else Compl(x)


CASES = [
    # The hard-fought classics
    ("add-mul precedence", lambda a, b, c: a + b * c, (2, 3, 4)),
    ("mul-add precedence", lambda a, b, c: a * b + c, (2, 3, 4)),
    ("sub left assoc", lambda a, b, c: a - b - c, (10, 3, 2)),
    ("sub right nested", lambda a, b, c: a - (b - c), (10, 3, 2)),
    ("div left assoc", lambda a, b, c: a * b // c, (7, 6, 4)),
    ("div right nested", lambda a, b, c: a * (b // c), (7, 6, 4)),
    ("mul of sum", lambda a, b, c: a * (b + c), (2, 3, 4)),
    ("sums of products", lambda a, b, c: a * b + c * (a - b), (5, 3, 2)),
    ("deep mix", lambda a, b, c: a + b * (c - a) // (b + c), (2, 7, 5)),
    ("nested division", lambda a, b, c: a * (b // (c * a)), (2, 30, 3)),
    ("unary minus", lambda a, b, c: -a + b * c, (5, 2, 3)),
    ("negated sum", lambda a, b, c: -(a + b) * c, (5, 2, 3)),
    # Modulo
    ("mod basic", lambda a, b, c: a % b, (7, 3, 0)),
    ("mod in mul left", lambda a, b, c: a % b * c, (7, 3, 4)),
    ("mod in mul right", lambda a, b, c: a * (b % c), (7, 8, 3)),
    ("mod of sum", lambda a, b, c: (a + b) % c, (7, 8, 4)),
    # Power
    ("power basic", lambda a, b, c: a**b, (2, 5, 0)),
    ("power right assoc (python builds a**(b**c))", lambda a, b, c: a**b**c, (2, 3, 2)),
    ("power left grouped", lambda a, b, c: (a**b) ** c, (2, 3, 2)),
    ("power of sum", lambda a, b, c: (a + b) ** c, (1, 2, 3)),
    ("sum of powers", lambda a, b, c: a**b + c**a, (2, 3, 4)),
    ("python negative power: -(a**b)", lambda a, b, c: -(a**b), (2, 2, 0)),
    ("gringo negative power: (-a)**b", lambda a, b, c: (-a) ** b, (2, 2, 0)),
    # Bitwise
    ("and basic", lambda a, b, c: a & b, (6, 3, 0)),
    ("or basic", lambda a, b, c: a | b, (6, 3, 0)),
    ("xor basic", lambda a, b, c: a ^ b, (6, 3, 0)),
    ("and of sums", lambda a, b, c: (a + b) & c, (1, 2, 2)),
    ("sum of ands", lambda a, b, c: (a & b) + c, (6, 3, 2)),
    ("bitwise mix", lambda a, b, c: (a & b) | (b ^ c), (6, 3, 5)),
    ("complement", lambda a, b, c: compl(a), (5, 0, 0)),
    ("complement of sum", lambda a, b, c: compl(a + b), (5, 3, 0)),
    ("complement then and", lambda a, b, c: compl(a) & b, (5, 7, 0)),
]


@pytest.mark.parametrize("name,build,args", CASES, ids=[c[0] for c in CASES])
def test_clingo_evaluates_rendered_tree_identically(
    name: str, build: Callable[..., Any], args: tuple[int, ...]
) -> None:
    expected = build(*args)

    program = ASPProgram()
    Result = Predicate.define("result", ["value"])
    expression = build(*(Number(v) for v in args))
    program.fact(Result(value=expression))

    models = list(program.solve())
    assert len(models) == 1, f"{name}: rendered program was not satisfiable"
    values = [pred["value"].value for pred in models[0].atoms(Result)]
    assert values == [expected], (
        f"{name}: rendered {expression.render()!r}, clingo says {values}, python says {expected}"
    )


def test_defensive_parenthesization() -> None:
    """Power and bitwise operators are over-parenthesized on purpose."""
    a, b, c = Number(1), Number(2), Number(3)
    assert (a + b**c).render() == "1 + (2 ** 3)"
    assert (a**b**c).render() == "1 ** (2 ** 3)"  # right-associativity spelled out
    assert ((a**b) ** c).render() == "(1 ** 2) ** 3"
    assert ((a & b) | c).render() == "(1 & 2) ? 3"
    assert (a & (b | c)).render() == "1 & (2 ? 3)"
    assert ((a ^ b) & c).render() == "(1 ^ 2) & 3"
    assert ((a + b) & c).render() == "(1 + 2) & 3"
    assert ((a & b) + c).render() == "(1 & 2) + 3"


def test_minimal_parenthesization_for_classic_operators() -> None:
    """The familiar arithmetic keeps its hard-fought minimal parentheses."""
    a, b, c = Number(1), Number(2), Number(3)
    assert (a + b * c).render() == "1 + 2 * 3"
    assert (a - b - c).render() == "1 - 2 - 3"
    assert (a - (b - c)).render() == "1 - (2 - 3)"
    assert (a * b // c).render() == "1 * 2 / 3"
    assert (a * (b // c)).render() == "1 * (2 / 3)"
    assert (a * (b % c)).render() == "1 * (2 \\ 3)"
    assert (a % b * c).render() == "1 \\ 2 * 3"
    assert Compl(a).render() == "~1"


# --- direct render-string pins (formerly test_expression.py) ---


def test_basic_expression_rendering() -> None:
    """Test basic expression rendering with different operators."""
    X = Variable("X")
    Y = Variable("Y")
    c1 = Number(1)
    c2 = Number(2)

    # Basic operations
    assert (X + Y).render() == "X + Y"
    assert (X - Y).render() == "X - Y"
    assert (X * Y).render() == "X * Y"
    assert (X // Y).render() == "X / Y"  # Integer division

    # With constants
    assert (c1 + c2).render() == "1 + 2"
    assert (c1 * c2).render() == "1 * 2"

    # Unary operations
    assert (-X).render() == "-X"
    assert Abs(X).render() == "|X|"


def test_nested_expression_precedence() -> None:
    """Test that nested expressions respect operator precedence."""
    X = Variable("X")
    Y = Variable("Y")
    Z = Variable("Z")

    # Multiplication has higher precedence than addition
    assert (X + Y * Z).render() == "X + Y * Z"
    assert (X * Y + Z).render() == "X * Y + Z"

    # Division has same precedence as multiplication
    assert (X * Y // Z).render() == "X * Y / Z"  # No parens needed - evaluated left to right

    # Subtraction is non-commutative
    assert (X - Y - Z).render() == "X - Y - Z"  # No parens needed - evaluated left to right

    # Parentheses in original expression should be preserved
    expr = X * (Y + Z)
    assert expr.render() == "X * (Y + Z)"

    # More complex expressions
    expr = X * Y + Z * (X - Y)
    assert expr.render() == "X * Y + Z * (X - Y)"


def test_multiplication_division_interaction() -> None:
    """Test the specific case of multiplication and division interaction."""
    X = Variable("X")
    Y = Variable("Y")
    Z = Variable("Z")

    # This is crucial: A * B / C vs A * (B / C)
    # The first evaluates left-to-right as (A * B) / C
    # The second preserves the division first

    # Case 1: Left-to-right evaluation (default in ASP)
    expr1 = (X * Y) // Z
    assert expr1.render() == "X * Y / Z"

    # Case 2: Division first, then multiplication
    expr2 = X * (Y // Z)
    assert expr2.render() == "X * (Y / Z)"

    # Case 3: With constants and variables
    expr3 = 2 * (X - 3) // 3
    assert expr3.render() == "2 * (X - 3) / 3"

    # Case 4: A complicated case
    expr4 = 2 + (X - 2) // 3 + 3 * ((Y - 2) // 3)
    assert expr4.render() == "2 + (X - 2) / 3 + 3 * ((Y - 2) / 3)"


def test_deeply_nested_expressions() -> None:
    """Test deeply nested expressions that require careful parenthesization."""
    X = Variable("X")
    Y = Variable("Y")
    Z = Variable("Z")

    # Deep nesting with mixed operations
    expr = X + Y * (Z - X) // (Y + Z)
    assert expr.render() == "X + Y * (Z - X) / (Y + Z)"

    # Expression with deliberate parenthesization
    expr = X * (Y // (Z * X))
    assert expr.render() == "X * (Y / (Z * X))"

    # Expression with multiple operations of same precedence
    expr = X * Y // Z * X
    assert expr.render() == "X * Y / Z * X"  # Left-to-right evaluation


def test_precedence_with_subexpressions() -> None:
    """Test precedence handling with subexpressions."""
    X = Variable("X")
    Y = Variable("Y")
    Z = Variable("Z")

    expr1 = X - (Y - Z)
    assert expr1.render() == "X - (Y - Z)"

    expr2 = X + (Y - Z)
    assert expr2.render() == "X + Y - Z"
