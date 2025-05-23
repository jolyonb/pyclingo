from __future__ import annotations

from enum import Enum


class Operation(Enum):
    """Enum representing the mathematical operations in ASP."""

    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    INTEGER_DIVIDE = "/"  # ASP uses / for integer division
    UNARY_MINUS = "unary-"
    ABS = "abs"


UNARY_OPERATIONS = {Operation.UNARY_MINUS, Operation.ABS}
BINARY_OPERATIONS = {Operation.ADD, Operation.SUBTRACT, Operation.MULTIPLY, Operation.INTEGER_DIVIDE}
NONCOMMUTATIVE_OPERATIONS = {Operation.SUBTRACT, Operation.INTEGER_DIVIDE}


# Operator precedence (higher number = higher precedence)
PRECEDENCE = {
    Operation.UNARY_MINUS: 2,
    Operation.MULTIPLY: 1,
    Operation.INTEGER_DIVIDE: 1,
    Operation.ADD: 0,
    Operation.SUBTRACT: 0,
}


class ComparisonOperator(Enum):
    """Enum representing comparison operators in ASP."""

    EQUAL = "="
    NOT_EQUAL = "!="
    LESS_THAN = "<"
    LESS_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_EQUAL = ">="
