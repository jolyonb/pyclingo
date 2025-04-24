from __future__ import annotations

from enum import Enum


class Operation(Enum):
    """Enum representing the mathematical operations in ASP."""

    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    UNARY_MINUS = "unary-"
    ABS = "abs"


UNARY_OPERATIONS = {Operation.UNARY_MINUS, Operation.ABS}
BINARY_OPERATIONS = {Operation.ADD, Operation.SUBTRACT, Operation.MULTIPLY}
NONCOMMUTATIVE_OPERATIONRS = {Operation.SUBTRACT}


# Operator precedence (lower number = higher precedence)
PRECEDENCE = {
    Operation.UNARY_MINUS: 0,
    Operation.MULTIPLY: 1,
    Operation.ADD: 2,
    Operation.SUBTRACT: 2,
}


class ComparisonOperator(Enum):
    """Enum representing comparison operators in ASP."""

    EQUAL = "="
    NOT_EQUAL = "!="
    LESS_THAN = "<"
    LESS_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_EQUAL = ">="
