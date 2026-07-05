"""
The mutually-recursive operator cluster of pyclingo: terms, values, pools,
expressions, and comparisons. Operator methods on these classes construct
each other's classes (e.g. X + 1 builds an Expression, X == Y builds a
Comparison), so they are merged into one module to avoid deferred imports.
Everything else in the package imports downward from here.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Self, Sequence, Union, cast, overload

from pyclingo.operators import (
    BINARY_OPERATIONS,
    EXPLICIT_PARENS_OPERATIONS,
    NONCOMMUTATIVE_OPERATIONS,
    PRECEDENCE,
    UNARY_OPERATIONS,
    ComparisonOperator,
    Operation,
)

if TYPE_CHECKING:
    # The one annotation-only upward reference in the package: collect_predicates
    # returns predicate classes, but core cannot import predicate at runtime
    from pyclingo.predicate import PREDICATE_CLASS_TYPE


# Type aliases for the operator cluster
type EXPRESSION_FIELD_TYPE = Value | Expression | int
type VALUE_EXPRESSION_TYPE = Value | Expression
type NUMBER_LIKE = int | Number | DefinedConstant | Variable


class RenderingContext(Enum):
    """
    Enum for defining rendering contexts where predicates may need to know to surround themselves in parentheses.
    """

    DEFAULT = "default"
    LONE_PREDICATE_ARGUMENT = "lone_predicate_argument"
    NEGATION = "negation"
    IN_EXPRESSION = "in_expression"


class Term(ABC):
    """
    Abstract base class representing a term in an Answer Set Programming (ASP) program.

    This serves as the root class for all ASP term types in the hierarchy.
    """

    @abstractmethod
    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        """
        Renders the term as a string in Clingo syntax.

        Context tells the term where it is being rendered; terms are responsible
        for wrapping themselves in parentheses as needed.
        """
        pass

    @property
    @abstractmethod
    def is_grounded(self) -> bool:
        """Determines if the term is fully grounded (contains no variables)."""
        pass

    @abstractmethod
    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this term for use in a specific position, raising if invalid.

        Args:
            is_in_head: True if validating for head position, False for body position.
        """
        pass

    @abstractmethod
    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """Collects all Predicate classes (not instances) used in this term."""
        pass

    @abstractmethod
    def collect_defined_constants(self) -> set[str]:
        """Collects all defined constant names used in this term."""
        pass

    @abstractmethod
    def collect_variables(self) -> set[str]:
        """Collects the names of all variables used in this term."""
        pass


class BasicTerm(Term, ABC):
    """
    Abstract base class for terms that can be direct predicate arguments.

    This includes values (variables, constants) and predicates themselves.
    BasicTerms are the fundamental building blocks for constructing ASP programs.
    """


class ComparableTerm(Term, ABC):
    """
    Abstract base for terms that can appear in comparisons: Value, Expression, Aggregate.

    Provides the comparison operators (==, !=, <, <=, >, >=), which build Comparison
    terms rather than evaluating anything, and doubles as the isinstance marker for
    "may be a comparison operand". Terms outside this branch of the hierarchy
    (e.g. Predicate, Choice) cannot be compared directly; bind them to a Variable.
    """

    # Defining __eq__ sets __hash__ to None; restore identity hashing. Hash-based
    # containers (sets, dicts) work because they compare stored hash values before
    # calling __eq__. LIST/TUPLE membership does call __eq__ and therefore raises via
    # Comparison.__bool__ — loud, but a real restriction: use sets for containment.
    __hash__ = object.__hash__

    def __lt__(self, other: Any) -> Comparison:
        if not isinstance(other, (ComparableTerm, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.LESS_THAN, other)

    def __le__(self, other: Any) -> Comparison:
        if not isinstance(other, (ComparableTerm, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.LESS_EQUAL, other)

    def __gt__(self, other: Any) -> Comparison:
        if not isinstance(other, (ComparableTerm, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.GREATER_THAN, other)

    def __ge__(self, other: Any) -> Comparison:
        if not isinstance(other, (ComparableTerm, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.GREATER_EQUAL, other)

    def __eq__(self, other: Any) -> Comparison:  # type: ignore[override]
        if not isinstance(other, (ComparableTerm, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.EQUAL, other)

    def __ne__(self, other: Any) -> Comparison:  # type: ignore[override]
        if not isinstance(other, (ComparableTerm, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.NOT_EQUAL, other)


class AggregateBase(ComparableTerm, ABC):
    """
    Marker base for aggregates (#count, #sum, ...), which are defined in
    aggregates.py. It exists so code here can recognize aggregates with
    isinstance: aggregates.py imports downward from core, so core cannot
    import the Aggregate class itself.
    """


class Value(BasicTerm, ComparableTerm, ABC):
    """
    Abstract base class for values: variables and constants, the most basic
    elements in an ASP program.

    Value inherits from both branches of the term hierarchy because values play
    both roles: as BasicTerms they can be direct predicate arguments (the X in
    p(X)), and as ComparableTerms they can appear in comparisons (the X in
    X < 5). Arithmetic operators on values build Expression terms; comparison
    operators build Comparison terms.

    Concrete Value subclasses are cached: constructing the same value twice returns the
    same object, e.g. Variable("X") is Variable("X"). Values are immutable, so sharing
    is safe — and because equal values are the same object, sets and dicts of Values
    behave correctly even though __eq__ builds Comparison terms instead of comparing.
    """

    _cache: ClassVar[dict[tuple[type, type, Any], Value]] = {}

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        # All concrete Value subclasses take exactly one constructor argument; anything
        # else falls through so __init__ can raise its own error. The cache key includes
        # the argument's type so that equal-but-distinct-type arguments never share an
        # instance.
        if len(args) + len(kwargs) == 1:
            value = args[0] if args else next(iter(kwargs.values()))
            key = (cls, type(value), value)
            try:
                cached = Value._cache.get(key)
            except TypeError:
                # Unhashable constructor argument; let __init__ reject it with a clear error
                pass
            else:
                if cached is None:
                    cached = super().__new__(cls)
                    Value._cache[key] = cached
                return cast(Self, cached)
        return super().__new__(cls)

    @abstractmethod
    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        """
        Renders the value as a string in Clingo syntax.

        The arguments beyond context are ignored by values; they exist so that
        Expression can pass rendering state (parent operator and operand side)
        uniformly to all of its operands when deciding parenthesization.
        """
        pass

    def __add__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.ADD, other)

    def __radd__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.ADD, self)

    def __sub__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.SUBTRACT, other)

    def __rsub__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.SUBTRACT, self)

    def __mul__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.MULTIPLY, other)

    def __rmul__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.MULTIPLY, self)

    def __neg__(self) -> Expression:
        return Expression(None, Operation.UNARY_MINUS, self)

    def __floordiv__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.INTEGER_DIVIDE, other)

    def __rfloordiv__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.INTEGER_DIVIDE, self)

    def __mod__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.MODULO, other)

    def __rmod__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.MODULO, self)

    def __pow__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.POWER, other)

    def __rpow__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.POWER, self)

    def __and__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.BITAND, other)

    def __rand__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.BITAND, self)

    def __or__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.BITOR, other)

    def __ror__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.BITOR, self)

    def __xor__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(self, Operation.BITXOR, other)

    def __rxor__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        return Expression(other, Operation.BITXOR, self)

    def __invert__(self) -> Expression:
        """Bitwise complement (~X); distinct from ~predicate, which is default negation."""
        return Expression(None, Operation.COMPLEMENT, self)


class Variable(Value):
    """
    Represents a variable in an ASP program.

    Variables in ASP start with an uppercase letter or can be an underscore '_'
    for anonymous variables. A variable can bind to any term: a number (4), a
    string ("john"), or a compound term like cell(1, 2) — including nullary
    atoms like n, which pyclingo models as zero-arity predicates.
    """

    def __init__(self, name: str):
        if not name or (name != "_" and not name[0].isupper()):
            raise ValueError(f"Variable name must start with an uppercase letter or be '_': {name}")
        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Variable name can only contain letters, digits, and underscores: {name}")
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_anonymous(self) -> bool:
        """True if this is the anonymous variable '_'."""
        return self._name == "_"

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        return self._name

    @property
    def is_grounded(self) -> bool:
        """Variables are never grounded."""
        return False

    def validate_in_context(self, is_in_head: bool) -> None:
        """Variables can only appear as arguments, never standalone: always raises."""
        raise ValueError("Variables can only be used as arguments to predicates or other terms")

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        return set()

    def collect_defined_constants(self) -> set[str]:
        return set()

    def __repr__(self) -> str:
        return f"Variable({self._name!r})"

    def __str__(self) -> str:
        return self.name

    def collect_variables(self) -> set[str]:
        return {self.name}

    def in_(self, pool_or_range: Union[Pool, list, tuple, range]) -> Comparison:
        """
        Creates a comparison that binds this variable to a pool or range.

        This is a convenience method for creating terms like "X = 1..5" or
        "X = (1;3;5)" which are commonly used in ASP for domain restrictions.

        Args:
            pool_or_range: A Pool object, list/tuple of valid pool elements,
                          or a range object (converted to RangePool if step=1,
                          otherwise to ExplicitPool)

        Returns:
            Comparison: A comparison term representing "X = pool_or_range"

        Examples:
            >>> from pyclingo import RangePool
            >>> X = Variable("X")
            >>> X.in_(RangePool(1, 5)).render()
            'X = 1..5'
            >>> X.in_([1, 3, 5]).render()
            'X = (1; 3; 5)'
            >>> X.in_(range(1, 6)).render()
            'X = 1..5'
            >>> X.in_(range(1, 10, 2)).render()
            'X = (1; 3; 5; 7; 9)'

        Raises:
            TypeError: If pool_or_range is not a Pool, list, tuple or range,
                      or if elements in a list/tuple are not valid pool elements.
        """
        return Comparison(self, ComparisonOperator.EQUAL, pool(pool_or_range))


class ConstantBase(Value, ABC):
    """
    Abstract base class for constants in ASP programs.

    Constants are grounded values that can appear in predicates
    or directly in a program. This class serves as the foundation
    for both regular constants and defined constants.
    """

    @property
    def is_grounded(self) -> bool:
        """Constants are always grounded."""
        return True

    def validate_in_context(self, is_in_head: bool) -> None:
        """Constants can only appear as arguments, never standalone: always raises."""
        raise ValueError("Constants can only be used as arguments to predicates or other terms")

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        return set()

    def collect_defined_constants(self) -> set[str]:
        """Empty by default; DefinedConstant overrides to report its name."""
        return set()

    def collect_variables(self) -> set[str]:
        return set()


class Number(ConstantBase):
    """
    Represents a numeric constant in an ASP program.

    Numeric constants in ASP are integers that can be used directly
    or as arguments to predicates.
    """

    def __init__(self, value: int):
        # bool subclasses int, and a boolean is never a valid ASP term
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Number value must be an integer, got {type(value).__name__}")
        if not -(2**31) <= value < 2**31:
            raise ValueError(
                f"Number value {value} is outside clingo's integer range "
                f"[-2147483648, 2147483647]; clingo would silently wrap it"
            )
        self._value = value

    @property
    def value(self) -> int:
        return self._value

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"Number({self._value!r})"

    def __str__(self) -> str:
        return str(self.value)


class String(ConstantBase):
    """
    Represents a string constant in an ASP program.

    String constants are enclosed in quotes in ASP syntax.
    """

    def __init__(self, value: str):
        """No double quotes, backslashes, or newlines (no escaping support); single quotes are fine."""
        if not isinstance(value, str):
            raise TypeError(f"String constant value must be a string, got {type(value).__name__}")

        if '"' in value:
            raise ValueError(f"String constant cannot contain double quotes (no escaping support): {value}")
        if "\\" in value or "\n" in value or "\r" in value:
            raise ValueError(
                f"String constant cannot contain backslashes or newlines "
                f"(they break clingo's lexer; there is no escaping support): {value!r}"
            )

        self._value = value

    @property
    def value(self) -> str:
        return self._value

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        return f'"{self.value}"'

    def __repr__(self) -> str:
        return f"String({self._value!r})"

    def __str__(self) -> str:
        """The rendered ASP text, quotes included: "e" is a string, e is a symbol."""
        return f'"{self.value}"'


class DefinedConstant(ConstantBase):
    """
    Represents a #const-defined constant in an ASP program.

    A defined constant is a name given a value via ASPProgram.define_constant(),
    rendered as a "#const name = value." statement; occurrences are substituted
    at grounding.
    """

    def __init__(self, value: str):
        """value is the constant's name: lowercase first letter, then letters, digits, and underscores."""
        if not value or not value[0].islower():
            raise ValueError(f"Defined constant must start with a lowercase letter: {value}")

        if not all(c.isalnum() or c == "_" for c in value):
            raise ValueError(f"Defined constant can only contain letters, digits, and underscores: {value}")

        self._value = value

    @property
    def value(self) -> str:
        """The constant's name."""
        return self._value

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        return self.value

    def collect_defined_constants(self) -> set[str]:
        """Reports this constant's own name."""
        return {self.value}

    def __repr__(self) -> str:
        return f"DefinedConstant({self._value!r})"

    def __str__(self) -> str:
        return str(self.value)


class Pool(BasicTerm, ABC):
    """
    Abstract base class for pools in ASP programs.

    Pools represent collections of terms that can be used as arguments to predicates
    or in other contexts. ASP expands pools differently depending on where they appear:
    conjunctively in heads and disjunctively in bodies.
    """

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Bare pools are never valid rule elements: always raises. Pools belong
        inside predicates (p(1..5)) or on the right of comparisons (X = 1..5).
        """
        raise ValueError("Pools can only be used as arguments to predicates or in comparisons")


class RangePool(Pool):
    """
    Represents a range pool in ASP programs, like 1..5.

    Bounds must be integer-valued: ints, Numbers, #const-defined constants,
    or grounded integer Expressions.
    """

    def __init__(self, start: int | ConstantBase | Expression, end: int | ConstantBase | Expression):
        """
        Initialize a range pool with start and end values (both inclusive).

        Raises if either bound is of the wrong type or an ungrounded Expression.
        """
        # Convert integers to Number objects
        if isinstance(start, int):
            start = Number(start)
        if isinstance(end, int):
            end = Number(end)

        for label, bound in (("start", start), ("end", end)):
            if not isinstance(bound, (Number, DefinedConstant, Expression)):
                raise TypeError(
                    f"Range {label} must be an int, Number, DefinedConstant, or grounded "
                    f"Expression, got {type(bound).__name__}"
                )
            if isinstance(bound, Expression) and not bound.is_grounded:
                raise ValueError(f"Expression in range {label} must be grounded")

        self._start: ConstantBase | Expression = start
        self._end: ConstantBase | Expression = end

    @property
    def start(self) -> ConstantBase | Expression:
        """The starting value of the range (inclusive)."""
        return self._start

    @property
    def end(self) -> ConstantBase | Expression:
        """The ending value of the range (inclusive)."""
        return self._end

    @property
    def is_grounded(self) -> bool:
        """Always True: bounds are validated to be constants or grounded expressions."""
        return True

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        return f"{self.start.render()}..{self.end.render()}"

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """Range pools cannot contain predicates."""
        return set()

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        constants.update(self.start.collect_defined_constants())
        constants.update(self.end.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        """Range pools cannot contain variables."""
        return set()


class ExplicitPool(Pool):
    """
    Represents an explicit pool in ASP programs, like (1;2;3) or (a;b;c).

    Explicit pools can contain grounded basic terms (constants and predicates).
    """

    def __init__(self, elements: Sequence[int | str | BasicTerm]):
        """
        Initialize an explicit pool from a non-empty sequence of elements;
        ints and strs are coerced to Number and String.

        Raises if any element is of an unsupported type or an ungrounded basic term.
        """
        if not elements:
            raise ValueError("ExplicitPool cannot be empty")

        self._elements = []

        for element in elements:
            if isinstance(element, str):
                element = String(element)
            elif isinstance(element, int):
                element = Number(element)
            elif isinstance(element, BasicTerm) and not isinstance(element, Pool):
                if not element.is_grounded:
                    raise ValueError(f"Pool elements must be grounded: {element.render()}")
            else:
                raise TypeError(
                    f"Pool elements must be ints, strs, or grounded basic terms, got {type(element).__name__}"
                )

            self._elements.append(element)

    @property
    def elements(self) -> list[BasicTerm]:
        """The elements of the pool (a defensive copy)."""
        return self._elements.copy()

    @property
    def is_grounded(self) -> bool:
        """Always True: elements are validated to be constants or grounded predicates."""
        return True

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        """Renders as e.g. "(1; 3; 5)"; parentheses are dropped as a lone predicate argument."""
        elements_str = "; ".join(element.render() for element in self._elements)
        return elements_str if context == RenderingContext.LONE_PREDICATE_ARGUMENT else f"({elements_str})"

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        predicates = set()

        for element in self.elements:
            predicates.update(element.collect_predicates())

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        for element in self.elements:
            constants.update(element.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables = set()

        for element in self.elements:
            variables.update(element.collect_variables())

        return variables


def pool(elements: Union[range, Sequence[int | str | BasicTerm], Pool]) -> Pool:
    """
    Create a Pool object from a general variety of input options.

    Args:
        elements: A Pool object, range, or sequence of elements
                 (integers, strings, or grounded basic terms: constants and predicates)

    Returns:
        An appropriate Pool object (RangePool for continuous ranges, ExplicitPool otherwise)

    Examples:
        >>> pool(range(1, 6)).render()
        '1..5'
        >>> pool([1, 3, 5]).render()
        '(1; 3; 5)'
        >>> pool(["a", "b"]).render()
        '("a"; "b")'

    Raises:
        TypeError: If elements is not a supported type or contains unsupported elements
        ValueError: If attempting to create an empty pool
    """
    pool_elements: Sequence[BasicTerm]

    if isinstance(elements, Pool):
        return elements

    elif isinstance(elements, range):
        if len(elements) == 0:
            raise ValueError("Cannot create an empty pool from an empty range")
        if elements.step == 1:
            return RangePool(Number(elements.start), Number(elements.stop - 1))
        return ExplicitPool([Number(x) for x in elements])

    elif isinstance(elements, (list, tuple)):
        if not elements:
            raise ValueError("Cannot create an empty pool")

        pool_elements = []
        for element in elements:
            if isinstance(element, int):
                pool_elements.append(Number(element))
            elif isinstance(element, str):
                pool_elements.append(String(element))
            elif isinstance(element, BasicTerm) and not isinstance(element, Pool):
                # Ensure the element is grounded
                if not element.is_grounded:
                    raise ValueError(f"Pool elements must be grounded: {element.render()}")
                pool_elements.append(element)
            else:
                raise TypeError(
                    f"Pool elements must be ints, strs, or grounded basic terms, got {type(element).__name__}"
                )

        return ExplicitPool(pool_elements)

    else:
        raise TypeError(f"Expected Pool, list, tuple, or range, got {type(elements).__name__}")


class Expression(ComparableTerm):
    """
    Represents a mathematical expression in an ASP program.

    Expressions can be binary operations (e.g., X+Y, X*Z) or
    unary operations (e.g., -X).
    """

    def __init__(
        self,
        first_term: EXPRESSION_FIELD_TYPE | None,
        operator: Operation,
        second_term: EXPRESSION_FIELD_TYPE,
    ):
        """first_term is None for unary operations; int operands are coerced to Number."""
        if first_term is not None and not isinstance(first_term, (int, Value, Expression)):
            raise TypeError(f"first_term must be a Value or Expression, got {type(first_term).__name__}")
        if not isinstance(second_term, (int, Value, Expression)):
            raise TypeError(f"second_term must be a Value or Expression, got {type(second_term).__name__}")

        if first_term is None and operator not in UNARY_OPERATIONS:
            raise ValueError(f"Unsupported unary operator: {operator}")
        elif first_term is not None and operator not in BINARY_OPERATIONS:
            raise ValueError(f"Unsupported binary operator: {operator}")

        # Convert Python literals to ASP values
        self._first_term = None if first_term is None else self._convert_if_needed(first_term)
        self._operator = operator
        self._second_term = self._convert_if_needed(second_term)

    @staticmethod
    def _convert_if_needed(value: EXPRESSION_FIELD_TYPE) -> VALUE_EXPRESSION_TYPE:
        """Coerces Python ints to Number; Values and Expressions pass through."""
        if isinstance(value, (Value, Expression)):
            return value

        if isinstance(value, int):
            return Number(value)

        raise TypeError(f"Cannot convert {type(value).__name__} to an ASP term")

    @property
    def first_term(self) -> VALUE_EXPRESSION_TYPE | None:
        """The left term; None for unary operations."""
        return self._first_term

    @property
    def operator(self) -> Operation:
        return self._operator

    @property
    def second_term(self) -> VALUE_EXPRESSION_TYPE:
        return self._second_term

    @property
    def is_unary(self) -> bool:
        return self._operator in UNARY_OPERATIONS

    @property
    def is_grounded(self) -> bool:
        """An expression is grounded if all its operands are grounded."""
        if self.is_unary:
            return self.second_term.is_grounded
        assert self.first_term is not None
        return self.first_term.is_grounded and self.second_term.is_grounded

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        """
        Renders the expression as a string in Clingo syntax.

        Each expression renders itself with knowledge of how it sits with respect to its parents.
        Expressions should never look at how their children are situated.
        """
        # Handle unary operators first
        if self.operator == Operation.ABS:
            # No parentheses ever needed; absolute value has its own delimiters
            return f"|{self.second_term.render(RenderingContext.DEFAULT)}|"

        if self.operator in (Operation.UNARY_MINUS, Operation.COMPLEMENT):
            prefix = "-" if self.operator == Operation.UNARY_MINUS else "~"
            second_str = self.second_term.render(RenderingContext.DEFAULT, self.operator, False)
            expr = f"{prefix}{second_str}"
            # Need parentheses when it's inside another operation (abs never passes the operation through)
            needs_outer_parentheses = parent_op is not None
            return f"({expr})" if needs_outer_parentheses else expr

        # Must be a binary operation
        assert self.first_term is not None
        first_str = self.first_term.render(RenderingContext.IN_EXPRESSION, self.operator, False)
        second_str = self.second_term.render(RenderingContext.IN_EXPRESSION, self.operator, True)

        expr = f"{first_str} {self.operator.value} {second_str}"

        # Determine if parentheses are needed
        needs_parentheses = False
        if parent_op is not None and (
            self.operator in EXPLICIT_PARENS_OPERATIONS or parent_op in EXPLICIT_PARENS_OPERATIONS
        ):
            # Power and the bitwise operators are deliberately over-parenthesized:
            # any mix with a different operator gets explicit parentheses, and power
            # gets them even against itself so its right-associativity is spelled
            # out. Readers never need gringo's precedence table to parse our output.
            needs_parentheses = self.operator != parent_op or self.operator == Operation.POWER
        elif parent_op is not None:
            current_precedence = PRECEDENCE[self.operator]
            parent_precedence = PRECEDENCE[parent_op]

            if current_precedence < parent_precedence:
                # Current operation has lower precedence than parent - always needs parentheses
                needs_parentheses = True
            elif current_precedence > parent_precedence:
                # Current operation has higher precedence than parent - never needs parentheses
                needs_parentheses = False
            elif current_precedence == parent_precedence:
                # Same precedence - need to handle carefully
                if parent_op in NONCOMMUTATIVE_OPERATIONS:
                    # When we're on the right side of a non-commutative parent operation,
                    # we always need parentheses for an expression at the same precedence.
                    # e.g., a - (b - c)
                    needs_parentheses = is_right_operand

                # Special case: division or modulo within multiplication
                # (X * Y) / Z differs from X * (Y / Z), and likewise for modulo
                if self.operator in (Operation.INTEGER_DIVIDE, Operation.MODULO) and parent_op == Operation.MULTIPLY:
                    needs_parentheses = is_right_operand

        # Apply parentheses if needed
        return f"({expr})" if needs_parentheses else expr

    def validate_in_context(self, is_in_head: bool) -> None:
        """Expressions cannot appear standalone in rule heads or bodies: always raises."""
        raise ValueError("Expressions can only be used as parts of comparisons, assignments, or as predicate arguments")

    # Arithmetic operator methods
    def __add__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.ADD, other)

    def __radd__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.ADD, self)

    def __sub__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.SUBTRACT, other)

    def __rsub__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.SUBTRACT, self)

    def __mul__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.MULTIPLY, other)

    def __rmul__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.MULTIPLY, self)

    def __neg__(self) -> Expression:
        return Expression(None, Operation.UNARY_MINUS, self)

    def __floordiv__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.INTEGER_DIVIDE, other)

    def __rfloordiv__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.INTEGER_DIVIDE, self)

    def __mod__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.MODULO, other)

    def __rmod__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.MODULO, self)

    def __pow__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.POWER, other)

    def __rpow__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.POWER, self)

    def __and__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.BITAND, other)

    def __rand__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.BITAND, self)

    def __or__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.BITOR, other)

    def __ror__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.BITOR, self)

    def __xor__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(self, Operation.BITXOR, other)

    def __rxor__(self, other: EXPRESSION_FIELD_TYPE) -> Expression:
        return Expression(other, Operation.BITXOR, self)

    def __invert__(self) -> Expression:
        """Bitwise complement (~X); distinct from ~predicate, which is default negation."""
        return Expression(None, Operation.COMPLEMENT, self)

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        predicates = set()

        if self.first_term is not None:
            predicates.update(self.first_term.collect_predicates())

        predicates.update(self.second_term.collect_predicates())

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        if self.first_term is not None:
            constants.update(self.first_term.collect_defined_constants())

        constants.update(self.second_term.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables = set()

        if self.first_term is not None:
            variables.update(self.first_term.collect_variables())

        variables.update(self.second_term.collect_variables())

        return variables


class Comparison(Term):
    """
    Represents a comparison between two terms in an ASP program.

    Comparisons can be equality (=), inequality (!=), or
    relational comparisons (<, <=, >, >=).
    """

    _left_term: ComparableTerm
    _right_term: ComparableTerm | Pool

    def __init__(
        self,
        left_term: Union[int, str, Term],
        operator: ComparisonOperator,
        right_term: Union[int, str, Term],
    ):
        """
        int and str operands are coerced to Number and String.

        A Pool may only appear on the right, compared by equality against a variable.
        """
        # Convert Python literals to ASP values
        if isinstance(left_term, int):
            self._left_term = Number(left_term)
        elif isinstance(left_term, str):
            self._left_term = String(left_term)
        elif isinstance(left_term, ComparableTerm):
            self._left_term = left_term
        else:
            raise TypeError(
                f"Left term must be an int, str, or comparable term (Value, Expression, or Aggregate), "
                f"got {type(left_term).__name__}"
            )

        if isinstance(right_term, int):
            self._right_term = Number(right_term)
        elif isinstance(right_term, str):
            self._right_term = String(right_term)
        elif isinstance(right_term, (ComparableTerm, Pool)):
            self._right_term = right_term
        else:
            raise TypeError(
                f"Right term must be an int, str, comparable term (Value, Expression, or Aggregate), or Pool, "
                f"got {type(right_term).__name__}"
            )

        if not isinstance(operator, ComparisonOperator):
            raise TypeError(f"Comparison operator must be a ComparisonOperator, got {type(operator).__name__}")
        self._operator = operator

        if isinstance(right_term, Pool) and operator != ComparisonOperator.EQUAL:
            raise ValueError("A pool can only be compared using equality")

        if isinstance(right_term, Pool) and not isinstance(left_term, Variable):
            raise ValueError("A comparison involving a pool must have a variable on the left")

    @property
    def left_term(self) -> ComparableTerm:
        return self._left_term

    @property
    def operator(self) -> ComparisonOperator:
        return self._operator

    @property
    def right_term(self) -> ComparableTerm | Pool:
        return self._right_term

    def __bool__(self) -> bool:
        """
        Comparisons deliberately have no truth value.

        Operators like == on pyclingo terms build ASP comparison terms rather than
        evaluating anything, so code like `if x == y:` is almost certainly a bug.
        Raising here turns that silent wrongness into a loud error.
        """
        raise TypeError(
            f"A Comparison ({self.render()}) has no boolean value: comparison operators on "
            "pyclingo terms build ASP terms rather than evaluating them. If you meant to "
            "compare Python objects, compare their .render() output or use 'is'."
        )

    @property
    def is_grounded(self) -> bool:
        """A comparison is grounded if both its terms are grounded."""
        return self.left_term.is_grounded and self.right_term.is_grounded

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        left_str = self.left_term.render()
        right_str = self.right_term.render()

        expr = f"{left_str} {self.operator.value} {right_str}"

        return f"({expr})" if context == RenderingContext.NEGATION else expr

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Comparisons are valid in both rule bodies and rule heads: a comparison head
        like `C1 = C2 :- body` means the body forces the equality to hold.
        Comparisons involving aggregates are body-only: clingo rejects them in
        heads with a misleading "unsafe variables" error, so raise honestly here.
        """
        if is_in_head and any(isinstance(term, AggregateBase) for term in (self._left_term, self._right_term)):
            raise ValueError(
                "Comparisons involving aggregates cannot be rule heads; "
                "compute the aggregate in a body condition instead"
            )

    @property
    def is_assignment(self) -> bool:
        """Whether this comparison assigns a variable: Variable = value."""
        return self.operator == ComparisonOperator.EQUAL and isinstance(self.left_term, Variable)

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        predicates = set()

        predicates.update(self.left_term.collect_predicates())
        predicates.update(self.right_term.collect_predicates())

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        constants.update(self.left_term.collect_defined_constants())
        constants.update(self.right_term.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        variables = set()

        variables.update(self.left_term.collect_variables())
        variables.update(self.right_term.collect_variables())

        return variables


def Abs(term: EXPRESSION_FIELD_TYPE) -> Expression:
    """Builds an absolute-value expression, |term|."""
    return Expression(None, Operation.ABS, term)


ANY = Variable("_")


@overload
def create_variables(names: str) -> Variable: ...


@overload
def create_variables(*names: str) -> tuple[Variable, ...]: ...


def create_variables(*names: str) -> Variable | tuple[Variable, ...]:  # type: ignore[misc]
    """
    Create one or more ASP variables with the given names.

    Returns a single Variable if one name is provided, otherwise a tuple of Variables.
    """
    if not names:
        raise ValueError("At least one variable name must be provided")
    variables = tuple(Variable(name) for name in names)
    return variables[0] if len(names) == 1 else variables
