from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Self, Union, cast, overload

from pyclingo.comparison_mixin import ComparisonMixin
from pyclingo.operators import Operation
from pyclingo.term import BasicTerm, RenderingContext

if TYPE_CHECKING:
    from pyclingo.expression import Comparison, Expression
    from pyclingo.pool import Pool
    from pyclingo.types import PREDICATE_CLASS_TYPE, VALUE_EXPRESSION_TYPE


class Value(BasicTerm, ComparisonMixin, ABC):
    """
    Abstract base class for values that can be used as arguments in ASP programs.

    Values include variables and constants, representing the most basic
    elements in an ASP program.

    Concrete Value subclasses are cached: constructing the same value twice returns the
    same object, e.g. Variable("X") is Variable("X"). Values are immutable, so sharing
    is safe — and because equal values are the same object, sets and dicts of Values
    behave correctly even though __eq__ builds Comparison terms instead of comparing.
    """

    _cache: ClassVar[dict[tuple[type, type, Any], "Value"]] = {}

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
        Renders the term as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.
            Other arguments are ignored, but present to assist with rendering of expressions.

        Returns:
            str: The string representation of the value.
        """
        pass

    def __add__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        """
        Creates an Expression representing self + other.

        Args:
            other: The right-hand operand (integer or Term).

        Returns:
            Expression: A new Expression representing the addition.
        """
        from pyclingo.expression import Expression

        return Expression(self, Operation.ADD, other)

    def __radd__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        """
        Creates an Expression representing other + self.

        Args:
            other: The left-hand operand (integer or Term).

        Returns:
            Expression: A new Expression representing the addition.
        """
        from pyclingo.expression import Expression

        return Expression(other, Operation.ADD, self)

    def __sub__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        """
        Creates an Expression representing self - other.

        Args:
            other: The right-hand operand (integer or Term).

        Returns:
            Expression: A new Expression representing the subtraction.
        """
        from pyclingo.expression import Expression

        return Expression(self, Operation.SUBTRACT, other)

    def __rsub__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        """
        Creates an Expression representing other - self.

        Args:
            other: The left-hand operand (integer or Term).

        Returns:
            Expression: A new Expression representing the subtraction.
        """
        from pyclingo.expression import Expression

        return Expression(other, Operation.SUBTRACT, self)

    def __mul__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        """
        Creates an Expression representing self * other.

        Args:
            other: The right-hand operand (integer or Term).

        Returns:
            Expression: A new Expression representing the multiplication.
        """
        from pyclingo.expression import Expression

        return Expression(self, Operation.MULTIPLY, other)

    def __rmul__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        """
        Creates an Expression representing other * self.

        Args:
            other: The left-hand operand (integer or Term).

        Returns:
            Expression: A new Expression representing the multiplication.
        """
        from pyclingo.expression import Expression

        return Expression(other, Operation.MULTIPLY, self)

    def __neg__(self) -> Expression:
        """
        Creates an Expression representing -self.

        Returns:
            Expression: A new Expression representing the negation.
        """
        from pyclingo.expression import Expression

        return Expression(None, Operation.UNARY_MINUS, self)

    def __floordiv__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        """
        Creates an Expression representing self // other.

        Args:
            other: The right-hand operand (integer or Term).

        Returns:
            Expression: A new Expression representing the integer division.
        """
        from pyclingo.expression import Expression

        return Expression(self, Operation.INTEGER_DIVIDE, other)

    def __rfloordiv__(self, other: int | VALUE_EXPRESSION_TYPE) -> Expression:
        """
        Creates an Expression representing other // self.

        Args:
            other: The left-hand operand (integer or Term).

        Returns:
            Expression: A new Expression representing the integer division.
        """
        from pyclingo.expression import Expression

        return Expression(other, Operation.INTEGER_DIVIDE, self)


class Variable(Value):
    """
    Represents a variable in an ASP program.

    Variables in ASP start with an uppercase letter or can be an underscore '_'
    for anonymous variables. Variables may sometimes also refer to a predicate.
    """

    def __init__(self, name: str):
        """
        Initialize a variable with a name.

        Args:
            name: The name of the variable. Must either be '_' for an anonymous
                 variable or start with an uppercase letter.

        Raises:
            ValueError: If the name doesn't start with an uppercase letter and isn't '_'.
        """
        if not name or (name != "_" and not name[0].isupper()):
            raise ValueError(f"Variable name must start with an uppercase letter or be '_': {name}")
        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Variable name can only contain letters, digits, and underscores: {name}")
        self._name = name

    @property
    def name(self) -> str:
        """
        Gets the name of the variable.

        Returns:
            str: The name of the variable.
        """
        return self._name

    @property
    def is_anonymous(self) -> bool:
        """
        Determines if this is an anonymous variable ('_').

        Returns:
            bool: True if this is an anonymous variable, False otherwise.
        """
        return self._name == "_"

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        """
        Renders the term as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The string representation of the variable.
        """
        return self._name

    @property
    def is_grounded(self) -> bool:
        """
        Variables are never grounded by definition.

        Returns:
            bool: Always False for variables.
        """
        return False

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Variables themselves cannot directly appear in rule heads or bodies,
        but only as part of predicates or other terms.

        Args:
            is_in_head: True if validating for head position, False for body position.

        Raises:
            ValueError: When trying to validate a standalone variable in a rule.
        """
        raise ValueError("Variables can only be used as arguments to predicates or other terms")

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Variables don't directly reference predicates.

        Returns:
            set[type[Predicate]]: An empty set.
        """
        return set()

    def collect_defined_constants(self) -> set[str]:
        """
        Variables don't directly reference defined constants.

        Returns:
            set[str]: An empty set.
        """
        return set()

    def __repr__(self) -> str:
        """
        Generate a developer-friendly string representation.

        Returns:
            str: A readable representation showing the variable name
        """
        return f"Variable({self._name!r})"

    def __str__(self) -> str:
        """
        Returns the string representation of this Variable.

        Returns:
            str: A readable representation showing the variable name
        """
        return self.name

    def collect_variables(self) -> set[str]:
        """
        Returns this variable in a set.

        Returns:
            set[str]: A set containing this variable.
        """
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
        from pyclingo.expression import Comparison
        from pyclingo.operators import ComparisonOperator
        from pyclingo.pool import pool

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
        """
        Constants are always grounded by definition.

        Returns:
            bool: Always True for constants.
        """
        return True

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Constants themselves typically cannot directly appear in rule heads or bodies,
        but only as part of predicates or other terms.

        Args:
            is_in_head: True if validating for head position, False for body position.

        Raises:
            ValueError: When trying to validate a standalone constant in a rule.
        """
        raise ValueError("Constants can only be used as arguments to predicates or other terms")

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Constants don't directly reference predicates.

        Returns:
            set[type[predicate]]: An empty set.
        """
        return set()

    def collect_defined_constants(self) -> set[str]:
        """
        Default implementation for collecting defined constants.
        Subclasses should override this if they represent defined constants.

        Returns:
            set[str]: An empty set by default.
        """
        return set()

    def collect_variables(self) -> set[str]:
        """
        Constants don't contain variables.

        Returns:
            set[str]: An empty set.
        """
        return set()


class Number(ConstantBase):
    """
    Represents a numeric constant in an ASP program.

    Numeric constants in ASP are integers that can be used directly
    or as arguments to predicates.
    """

    def __init__(self, value: int):
        """
        Initialize a numeric constant with an integer value.

        Args:
            value: The integer value of the constant.

        Raises:
            TypeError: If the value is not an integer.
        """
        # bool subclasses int, and a boolean is never a valid ASP term
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Number value must be an integer, got {type(value).__name__}")
        self._value = value

    @property
    def value(self) -> int:
        """
        Gets the integer value of the constant.

        Returns:
            int: The value of the constant.
        """
        return self._value

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        """
        Renders the term as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The string representation of the constant.
        """
        return str(self.value)

    def __repr__(self) -> str:
        """
        Renders the constant as a string.

        Returns:
             str: The string representation of the constant.
        """
        return str(self.value)

    def __str__(self) -> str:
        """
        Renders the constant as a string.

        Returns:
             str: The string representation of the constant.
        """
        return str(self.value)


class String(ConstantBase):
    """
    Represents a string constant in an ASP program.

    String constants are enclosed in quotes in ASP syntax.
    """

    def __init__(self, value: str):
        """
        Initialize a string constant with a string value.

        Args:
            value: The string value of the constant.

        Raises:
            TypeError: If the value is not a string.
        """
        if not isinstance(value, str):
            raise TypeError(f"String constant value must be a string, got {type(value).__name__}")

        if '"' in value or "'" in value:
            raise ValueError(f"String constant cannot contain quotation marks: {value}")

        self._value = value

    @property
    def value(self) -> str:
        """
        Gets the string value of the constant.

        Returns:
            str: The value of the constant.
        """
        return self._value

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        """
        Renders the term as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The string representation of the constant.
        """
        return f'"{self.value}"'

    def __repr__(self) -> str:
        """
        Renders the constant as a string.

        Returns:
             str: The string representation of the constant.
        """
        return str(self.value)

    def __str__(self) -> str:
        """
        Renders the constant as a string.

        Returns:
             str: The string representation of the constant.
        """
        return str(self.value)


class DefinedConstant(ConstantBase):
    """
    Represents a #const-defined constant in an ASP program.

    A defined constant is a name given a value via ASPProgram.define_constant(),
    rendered as a "#const name = value." statement; occurrences are substituted
    at grounding. For a plain symbolic term needing no definition, use Symbol.
    """

    def __init__(self, value: str):
        """
        Initialize a defined constant with its name.

        Args:
            value: The name of the constant. Must start with a lowercase letter
                  and can contain letters, digits, and underscores.

        Raises:
            ValueError: If the value doesn't start with a lowercase letter or contains invalid characters.
        """
        if not value or not value[0].islower():
            raise ValueError(f"Defined constant must start with a lowercase letter: {value}")

        if not all(c.isalnum() or c == "_" for c in value):
            raise ValueError(f"Defined constant can only contain letters, digits, and underscores: {value}")

        self._value = value

    @property
    def value(self) -> str:
        """
        Gets the name of the defined constant.

        Returns:
            str: The name of the constant.
        """
        return self._value

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        """
        Renders the term as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The string representation of the symbolic constant.
        """
        return self.value

    def collect_defined_constants(self) -> set[str]:
        """
        Collects the defined constant name represented by this object.

        Returns:
            set[str]: A set containing this defined constant's name.
        """
        return {self.value}

    def __repr__(self) -> str:
        """
        Renders the constant as a string.

        Returns:
             str: The string representation of the constant.
        """
        return str(self.value)

    def __str__(self) -> str:
        """
        Renders the constant as a string.

        Returns:
             str: The string representation of the constant.
        """
        return str(self.value)


class Symbol(ConstantBase):
    """
    Represents a plain symbolic constant term, e.g. the n in direction(n).

    Unlike String, a Symbol renders unquoted — n and "n" are different
    terms in clingo. Unlike DefinedConstant, a Symbol is not a #const definition
    and needs no registration with the program; it is just a term.
    """

    def __init__(self, value: str):
        """
        Initialize a symbol.

        Args:
            value: The symbol name. Must start with a lowercase letter and can
                   contain letters, digits, and underscores.

        Raises:
            ValueError: If the name doesn't fit clingo's identifier syntax.
        """
        if not value or not value[0].islower():
            raise ValueError(f"Symbol must start with a lowercase letter: {value}")

        if not all(c.isalnum() or c == "_" for c in value):
            raise ValueError(f"Symbol can only contain letters, digits, and underscores: {value}")

        self._value = value

    @property
    def value(self) -> str:
        """Gets the name of the symbol."""
        return self._value

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        """
        Renders the term as a string in Clingo syntax.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The symbol, unquoted.
        """
        return self._value

    def __repr__(self) -> str:
        return f"Symbol({self._value!r})"

    def __str__(self) -> str:
        return self._value


ANY = Variable("_")


@overload
def create_variables(names: str) -> Variable: ...


@overload
def create_variables(*names: str) -> tuple[Variable, ...]: ...


def create_variables(*names: str) -> Variable | tuple[Variable, ...]:  # type: ignore[misc]
    """
    Create one or more ASP variables with the given names.

    Args:
        *names: Variable names

    Returns:
        A single Variable if one name is provided, otherwise a tuple of Variables
    """
    if not names:
        raise ValueError("At least one variable name must be provided")
    variables = tuple(Variable(name) for name in names)
    return variables[0] if len(names) == 1 else variables
