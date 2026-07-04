from __future__ import annotations

from typing import TYPE_CHECKING, Type, Union

if TYPE_CHECKING:
    from pyclingo.aggregates import Aggregate
    from pyclingo.core import DefinedConstant, Expression, Number, Pool, Value, Variable
    from pyclingo.predicate import Predicate

    PREDICATE_RAW_INPUT_TYPE = Union[int, str, Value, Predicate, Expression, Pool]
    PREDICATE_FIELD_TYPE = Union[Value, Predicate, Expression, Pool]

    EXPRESSION_FIELD_TYPE = Union[Value, Expression, int]
    VALUE_EXPRESSION_TYPE = Union[Value, Expression]
    COMPARISON_TERM_TYPE = Union[Value, Expression, Aggregate]

    PREDICATE_CLASS_TYPE = Type[Predicate]

    VARIABLE_TYPE = Variable

    NUMBER_LIKE = Union[int, Number, DefinedConstant, Variable]
