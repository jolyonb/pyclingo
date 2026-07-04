from __future__ import annotations

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
    COMPLEMENT = "~"  # Python: ~ on values/expressions (on predicates, ~ is default negation)
    ABS = "abs"  # Python: Abs(x)  (ASP spells absolute value |x|)


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
NONCOMMUTATIVE_OPERATIONS = {Operation.SUBTRACT, Operation.INTEGER_DIVIDE, Operation.MODULO, Operation.POWER}

# Rendering is deliberately over-parenthesized for these: any mix with a different
# operator (and power even with itself) gets explicit parentheses, so readers never
# need gringo's bitwise/power precedence table to parse our output
EXPLICIT_PARENS_OPERATIONS = {Operation.POWER, Operation.BITAND, Operation.BITOR, Operation.BITXOR}

# Operator precedence (higher number = higher precedence), established empirically
# against gringo (tests/pyclingo/test_arithmetic.py pins these): xor is loosest,
# then or, and, additive, multiplicative, power (right-associative), unary.
# Note unary minus binds TIGHTER than ** in gringo, unlike Python.
PRECEDENCE = {
    Operation.BITXOR: 0,
    Operation.BITOR: 1,
    Operation.BITAND: 2,
    Operation.ADD: 3,
    Operation.SUBTRACT: 3,
    Operation.MULTIPLY: 4,
    Operation.INTEGER_DIVIDE: 4,
    Operation.MODULO: 4,
    Operation.POWER: 5,
    Operation.UNARY_MINUS: 6,
    Operation.COMPLEMENT: 6,
}


class ComparisonOperator(Enum):
    """Enum representing comparison operators in ASP."""

    EQUAL = "="
    NOT_EQUAL = "!="
    LESS_THAN = "<"
    LESS_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_EQUAL = ">="
