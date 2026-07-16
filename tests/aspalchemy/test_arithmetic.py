"""
Arithmetic rendering pinned against clingo's actual evaluation.

Each case builds an expression tree twice from one lambda: once over aspalchemy
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

import copy
import pickle
from collections.abc import Callable
from typing import Any

import pytest

from aspalchemy import (
    ASPProgram,
    Compl,
    Expression,
    Not,
    Number,
    Operation,
    Predicate,
    RangePool,
    String,
    Variable,
)


def compl(x: Any) -> Any:
    """Bitwise complement for the dual-use case table: ~ on ints, Compl on terms."""
    return ~x if isinstance(x, int) else Compl(x)


def neg(x: Any) -> Any:
    """Unary minus as a function — a nested `-(-x)` is spelled neg(neg(x)) (ruff bans the `--`)."""
    return -x


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
    # The multiplicative-level regrouping trap: a right * operand hiding a
    # division (or modulo) on its left spine. Regrouped left-associatively
    # these compute different values, so the parentheses are load-bearing.
    ("mul right nested hiding div", lambda a, b, c: a * (b // c * a), (5, 7, 3)),
    ("mul right nested hiding mod", lambda a, b, c: a * (b % c * a), (5, 7, 3)),
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
    # Negative right operands: the additive fold (X + -1 renders X - 1) must
    # be value-preserving, so clingo's answer still matches Python's
    ("add of negated term", lambda a, b, c: a + (-b), (5, 3, 0)),
    ("sub of negated term", lambda a, b, c: a - (-b), (5, 3, 0)),
    ("add of negative literal", lambda a, b, c: a + b, (5, -3, 0)),
    ("sub of negative literal", lambda a, b, c: a - b, (5, -3, 0)),
    ("negated negative literal", lambda a, b, c: a + (-b), (5, -3, 0)),
    ("negative literal times", lambda a, b, c: a * b, (5, -3, 0)),
    ("negated sum folded", lambda a, b, c: a - (-(b + c)), (5, 3, 4)),
    ("folded inside product", lambda a, b, c: (a + (-b)) * c, (5, 3, 4)),
    ("folded under subtraction", lambda a, b, c: a - (b + (-c)), (5, 3, 4)),
    # Doubled unary operators: the two involutions collapse to the inner term
    # and abs collapses to one abs, under EVERY parent — all value-preserving,
    # so clingo's answer still matches Python's
    ("double negated term", lambda a, b, c: a + neg(neg(b)), (5, 3, 0)),
    ("double negated under product", lambda a, b, c: a * neg(neg(b)), (5, 3, 0)),
    ("double complement", lambda a, b, c: a + compl(compl(b)), (5, 3, 0)),
    ("triple negation", lambda a, b, c: a + neg(neg(neg(b))), (5, 3, 0)),
    ("doubled abs", lambda a, b, c: a + abs(abs(b)), (5, -3, 0)),
    ("mixed unary stack", lambda a, b, c: a + neg(compl(compl(b))), (5, 3, 0)),
    # The collapse must not discard load-bearing parentheses: before 1.4.1,
    # collapsing the doubled unary here handed the bare div-hiding tree to
    # the outer *, which rendered it unparenthesized — a different value
    ("double negation over the mul trap", lambda a, b, c: a * neg(neg(b // c * a)), (5, 7, 3)),
    ("double complement over the mul trap", lambda a, b, c: a * compl(compl(b // c * a)), (5, 7, 3)),
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
    # hard stop while every sibling worked or taught
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


def test_multiplicative_right_operand_keeps_its_parentheses() -> None:
    # A right operand at the multiplicative level always keeps its
    # parentheses — not only a / or \ child, but a * child too, whose left
    # spine may hide a division: 5 * ((7 / 3) * 2) is 20, while regrouped
    # 5 * 7 / 3 * 2 is 22. Checking only the immediate child's operator
    # missed this class entirely (fixed in 1.4.1).
    inner = (Number(7) // Number(3)) * Number(2)
    assert (Number(5) * inner).render() == "5 * (7 / 3 * 2)"
    # The involution collapse must land on this same render: before 1.4.1,
    # collapsing -(-x)/Compl(Compl(x)) discarded the doubled unary's
    # protective parentheses along with the operators, changing the value.
    assert (Number(5) * neg(neg(inner))).render() == "5 * (7 / 3 * 2)"
    assert (Number(5) * Compl(Compl(inner))).render() == "5 * (7 / 3 * 2)"
    # A right-grouped pure * chain keeps the caller's grouping (regrouping
    # it would be value-safe, but the parentheses echo the tree built)...
    assert (Number(5) * (Number(3) * Number(2))).render() == "5 * (3 * 2)"
    # ...and left-nested chains stay minimal, division included.
    assert (Number(5) * Number(3) * Number(2)).render() == "5 * 3 * 2"
    assert inner.render() == "7 / 3 * 2"


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


# --- the additive fold: a negative right operand normalizes into the operator ---


def test_negative_right_operand_folds_into_the_operator() -> None:
    """X + -1 is spelled X - 1: the sign moves into the operator at construction."""
    X, Y = Variable("X"), Variable("Y")

    assert (X + Number(-1)).render() == "X - 1"
    assert (X - Number(-1)).render() == "X + 1"
    assert (X + (-1)).render() == "X - 1"  # the Python-int path, coerced then folded
    assert (X - (-1)).render() == "X + 1"
    assert (X + (-Y)).render() == "X - Y"
    assert (X - (-Y)).render() == "X + Y"


def test_the_fold_repeats_to_a_fixpoint() -> None:
    """
    One pass is not enough: unwrapping a unary minus can expose a negative
    literal, which folds in turn. (A doubled unary minus never reaches the
    fold — the collapse below eats it first.)
    """
    X = Variable("X")

    assert (X + (-Number(-1))).render() == "X + 1"  # unwrap, then fold the literal
    assert (X - (-Number(-1))).render() == "X - 1"


def test_the_fold_is_confined_to_additive_operators() -> None:
    """Only + and - carry a sign in their symbol; every other operator keeps the literal."""
    X = Variable("X")

    assert (X * Number(-1)).render() == "X * -1"
    assert (X // Number(-2)).render() == "X / -2"
    assert (X % Number(-2)).render() == "X \\ -2"
    assert (X ** Number(-1)).render() == "X ** -1"
    assert (X & Number(-1)).render() == "X & -1"
    assert (X | Number(-1)).render() == "X ? -1"
    assert (X ^ Number(-1)).render() == "X ^ -1"
    assert (X * (-Number(1))).render() == "X * (-1)"


def test_the_fold_is_confined_to_the_right_operand() -> None:
    """A negative LEFT operand has no operator to fold into: it stays as written."""
    X, Y = Variable("X"), Variable("Y")

    assert (Number(-1) + X).render() == "-1 + X"
    assert (Number(-1) - X).render() == "-1 - X"
    assert ((-Y) + X).render() == "(-Y) + X"
    assert (X + Number(0)).render() == "X + 0"  # zero is not negative: untouched


def test_int32_min_does_not_fold() -> None:
    """Negating INT32_MIN leaves clingo's integer range, so there is no Number to fold to."""
    X = Variable("X")

    assert (X + Number(-2147483647)).render() == "X - 2147483647"  # the last that folds
    assert (X + Number(-2147483648)).render() == "X + -2147483648"  # the one that cannot
    assert (X - Number(-2147483648)).render() == "X - -2147483648"


def test_fold_reports_the_normalized_operator() -> None:
    """The normalization is visible, as with Not() on a plain comparison."""
    X = Variable("X")

    folded = X + Number(-1)
    assert folded.operator is Operation.SUBTRACT
    assert folded.second_term is Number(1)  # Values intern: identity is equality
    assert Expression(X, Operation.ADD, Number(-1)).operator is Operation.SUBTRACT
    assert (X - Number(-1)).operator is Operation.ADD
    assert (X + Number(1)).operator is Operation.ADD  # nothing to fold: operator as built


def test_parenthesization_survives_the_fold() -> None:
    """The folded operator drives parenthesization, so nesting still renders faithfully."""
    X, Y = Variable("X"), Variable("Y")
    A, B = Variable("A"), Variable("B")

    assert (X - (Y + Number(-1))).render() == "X - (Y - 1)"
    assert (X + (Y - Number(-1))).render() == "X + Y + 1"
    assert (X + (-(A - B))).render() == "X - (A - B)"
    assert (X - (-(A - B))).render() == "X + A - B"


def test_fold_shrinks_the_depth_it_unwraps() -> None:
    """Depth is recomputed after the fold, so the cap counts the operators we actually render."""
    X, Y = Variable("X"), Variable("Y")

    # X + (-Y) builds two nodes but renders one operator: the cap sees one level
    assert (X + (-Y))._depth == (X - Y)._depth

    expr: Expression | Variable = X
    for _ in range(Expression.MAX_DEPTH):
        expr = expr + (-1)  # each level folds to a single SUBTRACT node
    assert isinstance(expr, Expression)
    assert expr.render().count("-") == Expression.MAX_DEPTH
    with pytest.raises(ValueError, match="aggregate instead"):
        expr + (-1)


FOLD_EQUIVALENCE = [
    # (what the renderer used to emit, the tree that now renders it folded)
    ("5 + -3", lambda: Number(5) + Number(-3)),
    ("5 - -3", lambda: Number(5) - Number(-3)),
    ("5 + (-3)", lambda: Number(5) + (-Number(3))),
    ("5 - (-3)", lambda: Number(5) - (-Number(3))),
    ("5 + (-(4 - 9))", lambda: Number(5) + (-(Number(4) - Number(9)))),
    ("5 - (-(4 - 9))", lambda: Number(5) - (-(Number(4) - Number(9)))),
    ("5 - (4 + -3)", lambda: Number(5) - (Number(4) + Number(-3))),
    ("5 + (4 - -3)", lambda: Number(5) + (Number(4) - Number(-3))),
    ("(5 + -3) * 4", lambda: (Number(5) + Number(-3)) * Number(4)),
]


@pytest.mark.parametrize("old_text,build", FOLD_EQUIVALENCE, ids=[c[0] for c in FOLD_EQUIVALENCE])
def test_fold_preserves_the_value_clingo_computes(old_text: str, build: Callable[[], Expression]) -> None:
    """The fold is cosmetic: clingo evaluates the folded render exactly as it did the old one."""
    expression = build()
    assert expression.render() != old_text, "this case no longer exercises the fold"
    assert _clingo_evaluates(expression.render()) == _clingo_evaluates(old_text)


def _clingo_evaluates(term_text: str) -> int:
    """Grounds result(<term>) and reads back the integer clingo computed."""
    program = ASPProgram()
    Result = Predicate.define("result", ["value"])
    program.raw_asp(f"result({term_text}).", predicates=[Result])
    models = list(program.solve())
    assert len(models) == 1, f"{term_text!r}: program was not satisfiable"
    values = [pred["value"].value for pred in models[0].atoms(Result)]
    assert len(values) == 1
    return int(values[0])


# --- the double-unary collapse: the involutions vanish, abs is idempotent ---


def test_doubled_involutions_collapse_to_the_inner_term() -> None:
    """-(-X) IS X and Compl(Compl(X)) IS X: the node is gone, not merely hidden by the renderer."""
    X = Variable("X")

    assert neg(neg(X)).render() == "X"
    assert neg(neg(X)) is X
    assert compl(compl(X)).render() == "X"
    assert compl(compl(X)) is X
    assert not isinstance(neg(neg(X)), Expression)  # a Variable comes back, not an Expression

    inner = X + 1
    assert neg(neg(inner)) is inner  # the live inner tree is handed back
    assert neg(neg(inner)).render() == "X + 1"


def test_abs_is_idempotent_and_keeps_its_node() -> None:
    """||X|| parses in gringo and means |X|: abs keeps its node and adopts the inner operand."""
    X = Variable("X")

    folded = abs(abs(X))
    assert folded.render() == "|X|"
    assert isinstance(folded, Expression)
    assert folded.operator is Operation.ABS
    assert folded.second_term is X
    assert abs(abs(abs(X))).render() == "|X|"


def test_the_collapse_repeats_to_a_fixpoint() -> None:
    """Every doubled pair goes, however deep the stack — one collapse can expose the next."""
    X = Variable("X")

    assert neg(neg(neg(X))).render() == "-X"
    assert neg(neg(neg(neg(X)))).render() == "X"
    assert compl(compl(compl(X))).render() == "~X"
    assert neg(compl(compl(X))).render() == "-X"  # the doubled pair goes; the lone minus stays
    assert compl(neg(neg(compl(X)))) is X  # collapsing the inner pair exposes an outer one
    assert neg(compl(neg(compl(X)))).render() == "-(~(-(~X)))"  # alternating: nothing to collapse


def test_the_collapse_fires_on_the_raw_constructor_too() -> None:
    """Both doors normalize: the Python operators, and Expression(None, op, e) directly."""
    X = Variable("X")

    assert Expression(None, Operation.UNARY_MINUS, Expression(None, Operation.UNARY_MINUS, X)) is X
    assert Expression(None, Operation.COMPLEMENT, Expression(None, Operation.COMPLEMENT, X)) is X
    assert Expression(None, Operation.ABS, Expression(None, Operation.ABS, X)).render() == "|X|"


def test_the_collapse_hands_back_the_inner_node_unclobbered() -> None:
    """The returned node is the live inner one: the outer call's arguments must not overwrite it."""
    X, Y = Variable("X"), Variable("Y")

    inner = X + Y
    returned = Expression(None, Operation.UNARY_MINUS, Expression(None, Operation.UNARY_MINUS, inner))
    assert returned is inner
    assert isinstance(returned, Expression)
    assert returned.operator is Operation.ADD
    assert returned.render() == "X + Y"


def test_expressions_still_copy_and_pickle() -> None:
    """The class call is the only hook — copy, deepcopy, and pickle of an Expression keep working."""
    expression = Variable("X") + 1

    assert copy.deepcopy(expression).render() == "X + 1"
    assert copy.copy(expression).render() == "X + 1"
    assert pickle.loads(pickle.dumps(expression)).render() == "X + 1"


def test_the_collapse_fires_under_every_parent() -> None:
    """The old wart: -(-X) unwrapped only under an additive parent. The collapse is unconditional."""
    X, Y = Variable("X"), Variable("Y")

    assert (Y * neg(neg(X))).render() == "Y * X"
    assert (Y ** neg(neg(X))).render() == "Y ** X"
    assert (Y & compl(compl(X))).render() == "Y & X"
    assert abs(neg(neg(X))).render() == "|X|"
    assert (Y + neg(neg(X))).render() == "Y + X"  # and the additive parent still agrees
    assert (Y - neg(neg(X))).render() == "Y - X"
    assert (Y - neg(neg(neg(X)))).render() == "Y + X"  # collapse to -X, then the fold


def test_the_involutions_collapse_at_the_int32_floor() -> None:
    """
    No exception here, unlike the additive fold: clingo's unary minus wraps mod
    2**32, so -(-INT32_MIN) IS INT32_MIN. The fold's problem was that there is no
    legal Number to fold TO; the collapse needs none — it hands back the term itself.
    """
    X = Variable("X")
    floor = Number(-2147483648)

    assert neg(neg(floor)) is floor
    assert compl(compl(floor)) is floor
    assert neg(neg(floor)).render() == "-2147483648"
    assert (X + Number(-2147483648)).render() == "X + -2147483648"  # the fold still refuses this one


def test_the_collapse_shrinks_the_depth_it_removes() -> None:
    """A collapsed pair costs no depth: the cap counts the operators actually rendered."""
    X = Variable("X")

    inner = X + 1
    assert abs(abs(inner))._depth == abs(inner)._depth

    # A doubled unary cannot be built at all, so it cannot exhaust the cap either
    deep: Any = X
    for _ in range(Expression.MAX_DEPTH):
        deep = neg(neg(deep))
    assert deep is X


def test_default_negation_stays_doubled() -> None:
    """
    The contrast that makes the collapse principled: unary minus and ~ are
    involutions in clingo's ARITHMETIC, so a doubled pair is removable; default
    negation is not an involution on LITERALS, so not not p is preserved
    (test_negation.py owns that topic).
    """
    P = Predicate.define("p", [])
    p = P()

    assert Not(Not(p)).render() == "not not p"
    assert neg(neg(p)).render() == "p"  # classical negation on an atom, however, IS an involution


COLLAPSE_EQUIVALENCE = [
    # (what the renderer emitted before the collapse, the tree that now renders it collapsed)
    ("-(-7)", lambda: neg(neg(Number(7)))),
    ("~(~7)", lambda: compl(compl(Number(7)))),
    ("||-7||", lambda: abs(abs(Number(-7)))),
    ("-(-(-7))", lambda: neg(neg(neg(Number(7))))),
    ("5 + (-(-3))", lambda: Number(5) + neg(neg(Number(3)))),
    ("5 * (-(-3))", lambda: Number(5) * neg(neg(Number(3)))),
    # The int32 floor: the identity survives only because clingo wraps mod 2**32
    # — and it does survive, which is why there is no exception here
    ("-(--2147483648)", lambda: neg(neg(Number(-2147483648)))),
    ("~(~(-2147483648))", lambda: compl(compl(Number(-2147483648)))),
]


@pytest.mark.parametrize("old_text,build", COLLAPSE_EQUIVALENCE, ids=[c[0] for c in COLLAPSE_EQUIVALENCE])
def test_collapse_preserves_the_value_clingo_computes(old_text: str, build: Callable[[], Any]) -> None:
    """The collapse is cosmetic: clingo evaluates the collapsed render exactly as it did the old one."""
    term = build()
    assert term.render() != old_text, "this case no longer exercises the collapse"
    assert _clingo_evaluates(term.render()) == _clingo_evaluates(old_text)


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
    """A negated head is gringo sugar for a constraint; the error teaches the forbid spelling."""
    P = Predicate.define("p", ["a"])
    with pytest.raises(ValueError, match=r"does not model negated heads.*forbid\(\*body, p\)"):
        Not(P(a=1)).validate_in_context(True)


def test_expression_init_bad_first_term() -> None:
    with pytest.raises(TypeError, match="first_term"):
        Expression("x", Operation.ADD, 1)  # type: ignore[arg-type]


def test_expression_init_bad_second_term() -> None:
    with pytest.raises(TypeError, match="second_term"):
        Expression(1, Operation.ADD, "x")  # type: ignore[arg-type]


def test_expression_init_unary_operator_required_when_no_first_term() -> None:
    # The class-call overloads already refuse this pairing statically (a missing
    # first term admits only the unary operators); the runtime check is the pin
    with pytest.raises(ValueError, match="unary"):
        Expression(None, Operation.ADD, 1)  # type: ignore[arg-type]


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
    # / is the first division a Python user tries; the error points at //
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
