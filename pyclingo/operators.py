from enum import Enum


class Operation(Enum):
    """
    The mathematical operations in ASP.

    Each member notes the Python operator that builds it; where Python and ASP
    notation differ, both are given. Values hold the rendered ASP text.
    """

    ADD = "+"  # Python: +
    SUBTRACT = "-"  # Python: -
    MULTIPLY = "*"  # Python: *
    INTEGER_DIVIDE = "/"  # Python: //  (ASP spells integer division /)
    MODULO = "\\"  # Python: %  (ASP spells modulo \)
    POWER = "**"  # Python: **
    BITAND = "&"  # Python: &
    BITOR = "?"  # Python: |  (ASP spells bitwise or ?)
    BITXOR = "^"  # Python: ^
    UNARY_MINUS = "unary-"  # Python: unary -
    COMPLEMENT = "~"  # Python: Compl(x)  (~ itself is reserved for default negation)
    ABS = "abs"  # Python: abs(x)  (ASP spells absolute value |x|)


UNARY_OPERATIONS = {Operation.UNARY_MINUS, Operation.COMPLEMENT, Operation.ABS}
BINARY_OPERATIONS = {
    Operation.ADD,
    Operation.SUBTRACT,
    Operation.MULTIPLY,
    Operation.INTEGER_DIVIDE,
    Operation.MODULO,
    Operation.POWER,
    Operation.BITAND,
    Operation.BITOR,
    Operation.BITXOR,
}
# Named for the property, so POWER belongs even though the render path
# resolves every POWER pairing at the EXPLICIT_PARENS branch first
NONCOMMUTATIVE_OPERATIONS = {Operation.SUBTRACT, Operation.INTEGER_DIVIDE, Operation.MODULO, Operation.POWER}

# Rendering is deliberately over-parenthesized for these: any mix with a different
# operator (and power even with itself) gets explicit parentheses, so readers never
# need gringo's bitwise/power precedence table to parse our output
EXPLICIT_PARENS_OPERATIONS = {Operation.POWER, Operation.BITAND, Operation.BITOR, Operation.BITXOR}

# Operator precedence (higher number = higher precedence), established empirically
# against gringo (tests/pyclingo/test_arithmetic.py pins these): additive below
# multiplicative, unary tightest. Note unary minus binds TIGHTER than ** in
# gringo, unlike Python. Only operators OUTSIDE EXPLICIT_PARENS_OPERATIONS
# appear: those always parenthesize, so their precedence is never consulted.
PRECEDENCE = {
    Operation.ADD: 0,
    Operation.SUBTRACT: 0,
    Operation.MULTIPLY: 1,
    Operation.INTEGER_DIVIDE: 1,
    Operation.MODULO: 1,
    Operation.UNARY_MINUS: 2,
    Operation.COMPLEMENT: 2,
}


class ComparisonOperator(Enum):
    """Enum representing comparison operators in ASP."""

    EQUAL = "="
    NOT_EQUAL = "!="
    LESS_THAN = "<"
    LESS_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_EQUAL = ">="

    @property
    def inverse(self) -> ComparisonOperator:
        """
        The complementary operator: = and != swap, < pairs with >=, > with
        <=. Exact because clingo's term order is total — every ground
        comparison is either true or its inverse is.
        """
        return _INVERSE[self]


_INVERSE = {
    ComparisonOperator.EQUAL: ComparisonOperator.NOT_EQUAL,
    ComparisonOperator.NOT_EQUAL: ComparisonOperator.EQUAL,
    ComparisonOperator.LESS_THAN: ComparisonOperator.GREATER_EQUAL,
    ComparisonOperator.GREATER_EQUAL: ComparisonOperator.LESS_THAN,
    ComparisonOperator.GREATER_THAN: ComparisonOperator.LESS_EQUAL,
    ComparisonOperator.LESS_EQUAL: ComparisonOperator.GREATER_THAN,
}
