from pyclingo.expression import Abs
from pyclingo.value import Constant, Variable


def test_basic_expression_rendering() -> None:
    """Test basic expression rendering with different operators."""
    X = Variable("X")
    Y = Variable("Y")
    c1 = Constant(1)
    c2 = Constant(2)

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
