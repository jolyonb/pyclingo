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
from .choice import CardinalityType, Choice
from .clingo_handler import ClingoMessage, LogLevel
from .conditional_literal import ConditionalLiteral
from .conditioned_element import ConditionedElement, ConditionType
from .core import (
    ANY,
    INF,
    SUP,
    BasicTerm,
    ComparableTerm,
    Comparison,
    Compl,
    ConstantBase,
    DefaultNegation,
    DefinedConstant,
    ExplicitPool,
    Expression,
    Infimum,
    Negatable,
    Not,
    Number,
    Pool,
    PredicateOccurrence,
    RangePool,
    RenderingContext,
    String,
    Supremum,
    Term,
    V,
    Value,
    Variable,
    Vars,
    pool,
)
from .exceptions import GroundingError, PyClingoError, UnsatisfiableError
from .operators import ComparisonOperator, Operation
from .optimization import OptStrategy
from .predicate import Field, FieldAsTermType, NegatedSignature, Predicate, PredicateField, TupleTermType
from .program_elements import ProgramElement, RenderedLine
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
    PredicateTypes,
    RefinementSteps,
    Search,
    SolveResult,
    convert_predicate_to_symbol,
    convert_symbol_to_predicate,
)
from .solver import ASPProgram, GroundedProgram, SignatureGrounding
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
    "SignatureGrounding",
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
    "PyClingoError",
    "GroundingError",
    "UnsatisfiableError",
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
    "SUP",
    "INF",
    # Aggregates
    "Count",
    "Sum",
    "SumPlus",
    "Min",
    "Max",
    # Rule-building utilities
    "pool",
    "Not",
    "Compl",
    # Hierarchy types: these appear in public signatures and return types —
    # annotate with them; you rarely construct them directly
    "ConditionType",
    "ConditionedElement",
    "TupleTermType",
    "CardinalityType",
    "PredicateTypes",
    "FieldAsTermType",
    "PredicateOccurrence",
    "Term",
    "BasicTerm",
    "Value",
    "ConstantBase",
    "ComparableTerm",
    "Negatable",
    "ProgramElement",
    "Expression",
    "Comparison",
    "ComparisonOperator",
    "Operation",
    "RenderingContext",
    "DefaultNegation",
    "DefinedConstant",
    "Aggregate",
    "Pool",
    "Number",
    "String",
    "Supremum",
    "Infimum",
    # Interop with raw clingo symbols
    "convert_predicate_to_symbol",
    "convert_symbol_to_predicate",
    # Metadata
    "__version__",
]
