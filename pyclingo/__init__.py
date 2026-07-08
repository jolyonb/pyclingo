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
    V,
    Value,
    Variable,
    Vars,
    create_variables,
    pool,
)
from .operators import ComparisonOperator
from .optimization import OptStrategy
from .predicate import Field, Predicate, PredicateField
from .program_elements import Segment
from .solve_result import (
    AtomCollection,
    BraveConsequences,
    CautiousConsequences,
    Consequences,
    CostedModel,
    Model,
    OptimizeSteps,
    Optimum,
    RefinementSteps,
    SearchABC,
    SolveResult,
)
from .solver import ASPProgram, GroundedProgram
from .version import __version__

__all__ = [  # noqa: RUF022 (categorized deliberately, not sorted)
    # The program and its results
    "ASPProgram",
    "Segment",
    "GroundedProgram",
    "SolveResult",
    "Model",
    "CostedModel",
    "AtomCollection",
    "Consequences",
    "BraveConsequences",
    "CautiousConsequences",
    "RefinementSteps",
    "OptimizeSteps",
    "Optimum",
    "OptStrategy",
    "SearchABC",
    "LogLevel",
    "ClingoMessage",
    # Declaring predicates
    "Predicate",
    "Field",
    "PredicateField",
    # Rule-building objects
    "Variable",
    "ANY",
    "V",
    "Vars",
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
