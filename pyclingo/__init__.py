"""
PyClingo: A Python library for building clingo ASP (Answer Set Programming) programs
with a clean, object-oriented interface.
"""

from .aggregates import (
    Aggregate,
    Count,
    Max,
    Min,
    Sum,
    SumPlus,
)
from .choice import Choice
from .clingo_handler import ClingoMessage, LogLevel
from .conditional_literal import ConditionalLiteral
from .conditioned_element import CONDITION_TYPE
from .core import (
    ANY,
    Abs,
    Comparison,
    Compl,
    DefaultNegation,
    DefinedConstant,
    ExplicitPool,
    Expression,
    Not,
    Number,
    Pool,
    RangePool,
    String,
    Term,
    Value,
    Variable,
    create_variables,
    pool,
)
from .operators import ComparisonOperator
from .predicate import Field, Predicate, PredicateField
from .solve_result import Model, SolveResult
from .solver import ASPProgram
from .version import __version__

__all__ = [  # noqa: RUF022 (categorized deliberately, not sorted)
    # The program and its results
    "ASPProgram",
    "SolveResult",
    "Model",
    "LogLevel",
    "ClingoMessage",
    # Declaring predicates
    "Predicate",
    "Field",
    "PredicateField",
    # Rule-building objects
    "Variable",
    "ANY",
    "Choice",
    "ConditionalLiteral",
    "RangePool",
    "ExplicitPool",
    # Aggregates
    "Count",
    "Sum",
    "SumPlus",
    "Min",
    "Max",
    # Rule-building utilities
    "create_variables",
    "pool",
    "Not",
    "Abs",
    "Compl",
    # Hierarchy types: these appear in public signatures and return types —
    # annotate with them; you rarely construct them directly
    "CONDITION_TYPE",
    "Term",
    "Value",
    "Expression",
    "Comparison",
    "ComparisonOperator",
    "DefaultNegation",
    "DefinedConstant",
    "Aggregate",
    "Pool",
    "Number",
    "String",
    # Metadata
    "__version__",
]
