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

from pyclingo import (
    ASPProgram,
    Compl,
    Expression,
    Not,
    Number,
    Predicate,
    RangePool,
    String,
    Variable,
)
from pyclingo.operators import Operation


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


def test_abs_builtin_builds_the_abs_expression() -> None:
    # abs(X) is |X|, exactly Abs(X) — the one Python spelling that was a
    # stone wall while every sibling worked or taught
    X = Variable("X")
    assert abs(X).render() == "|X|"
    assert abs(X + 1).render() == "|X + 1|"


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
    assert abs(X).render() == "|X|"


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


# --- error paths and reflected operators (core.py) ---


def test_invert_on_value_directs_to_compl() -> None:
    """~ on a Value is reserved for default negation, not bitwise complement."""
    with pytest.raises(TypeError, match="Compl"):
        ~Variable("X")


def test_invert_on_expression_directs_to_compl() -> None:
    """~ on an Expression is reserved for default negation, not bitwise complement."""
    with pytest.raises(TypeError, match="Compl"):
        ~(Variable("X") + 1)


def test_variable_validate_in_context_raises() -> None:
    """A bare variable is never a valid standalone rule element."""
    with pytest.raises(ValueError, match="arguments to predicates"):
        Variable("X").validate_in_context(False)


def test_constant_validate_in_context_raises() -> None:
    """A bare constant is never a valid standalone rule element."""
    with pytest.raises(ValueError, match="arguments to predicates"):
        Number(5).validate_in_context(False)
    with pytest.raises(ValueError, match="arguments to predicates"):
        String("hi").validate_in_context(False)


def test_pool_validate_in_context_raises() -> None:
    """A bare pool belongs inside a predicate or on the right of a comparison."""
    with pytest.raises(ValueError, match="Pools can only be used"):
        RangePool(1, 5).validate_in_context(False)


def test_expression_validate_in_context_raises() -> None:
    """A bare expression is never a valid standalone rule element."""
    with pytest.raises(ValueError, match="parts of comparisons"):
        (Variable("X") + 1).validate_in_context(False)


def test_default_negation_rejected_in_head() -> None:
    """Default negation is body-only and raises when placed in a rule head."""
    P = Predicate.define("p", ["a"])
    with pytest.raises(ValueError, match="cannot be used in rule heads"):
        Not(P(a=1)).validate_in_context(True)


def test_expression_init_bad_first_term() -> None:
    with pytest.raises(TypeError, match="first_term"):
        Expression("x", Operation.ADD, 1)  # type: ignore[arg-type]


def test_expression_init_bad_second_term() -> None:
    with pytest.raises(TypeError, match="second_term"):
        Expression(1, Operation.ADD, "x")  # type: ignore[arg-type]


def test_expression_init_unary_operator_required_when_no_first_term() -> None:
    with pytest.raises(ValueError, match="unary"):
        Expression(None, Operation.ADD, 1)


def test_expression_init_binary_operator_required_with_first_term() -> None:
    with pytest.raises(ValueError, match="binary"):
        Expression(1, Operation.UNARY_MINUS, 2)


def test_expression_reflected_operators() -> None:
    """int OP Expression dispatches to Expression's reflected operator methods."""
    e = Variable("X") + Variable("Y")
    assert (1 - e).render() == "1 - (X + Y)"
    assert (10 // e).render() == "10 / (X + Y)"
    assert (10 % e).render() == "10 \\ (X + Y)"
    assert (2**e).render() == "2 ** (X + Y)"
    assert (1 & e).render() == "1 & (X + Y)"
    assert (1 | e).render() == "1 ? (X + Y)"
    assert (1 ^ e).render() == "1 ^ (X + Y)"


def test_deep_expression_chain_rejected_at_construction() -> None:
    # The tree walkers recurse per nesting level, and Python's frame limit
    # would kill a ~1000-level chain with a raw RecursionError mid-walk;
    # the cap turns that into a teaching error on the accumulation line
    X = Variable("X")
    expr: Expression | Variable = X
    for _ in range(Expression.MAX_DEPTH):
        expr = expr + 1
    assert isinstance(expr, Expression)
    assert expr.render().count("+") == Expression.MAX_DEPTH  # at the cap: walkers still fine
    with pytest.raises(ValueError, match="aggregate instead"):
        expr + 1


def test_true_division_teaches_floordiv() -> None:
    # / is the first division a Python user tries; the wall points at //
    X = Variable("X")
    with pytest.raises(TypeError, match="clingo has no true division"):
        X / 2  # type: ignore[operator]
    with pytest.raises(TypeError, match="clingo has no true division"):
        2 / X  # type: ignore[operator]
    with pytest.raises(TypeError, match="clingo has no true division"):
        (X + 1) / 2  # type: ignore[operator]
    with pytest.raises(TypeError, match="clingo has no true division"):
        2 / (X + 1)  # type: ignore[operator]


def test_string_operands_rejected_at_construction() -> None:
    # clingo arithmetic over strings is undefined for EVERY program — and an
    # Expression used to smuggle a String past the cardinality, weight, and
    # range checks that each reject bare Strings
    X = Variable("X")
    with pytest.raises(TypeError, match="no arithmetic in clingo"):
        String("a") + 1
    with pytest.raises(TypeError, match="no arithmetic in clingo"):
        X + String("a")
    with pytest.raises(TypeError, match="no arithmetic in clingo"):
        abs(String("a"))
