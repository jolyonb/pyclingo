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
from .conditioned_element import ConditionType
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
    pool,
)
from .operators import ComparisonOperator
from .optimization import OptStrategy
from .predicate import Field, NegatedSignature, Predicate, PredicateField
from .program_elements import RenderedLine
from .segment import Segment, When
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
    Search,
    SolveResult,
)
from .solver import ASPProgram, GroundedProgram
from .source_location import (
    SourceLocation,
    attribute_to_caller,
    capture_location,
    location_override,
    register_skip_package,
)
from .version import __version__

__all__ = [  # noqa: RUF022 (categorized deliberately, not sorted)
    # The program and its results
    "ASPProgram",
    "Segment",
    "When",
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
    "Search",
    "LogLevel",
    "ClingoMessage",
    "RenderedLine",
    # Source locations (diagnostics point at the authoring Python line)
    "SourceLocation",
    "capture_location",
    "register_skip_package",
    "attribute_to_caller",
    "location_override",
    # Declaring predicates
    "Predicate",
    "NegatedSignature",
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
    "pool",
    "Not",
    "Abs",
    "Compl",
    # Hierarchy types: these appear in public signatures and return types —
    # annotate with them; you rarely construct them directly
    "ConditionType",
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
