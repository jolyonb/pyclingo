"""
The mutually-recursive operator cluster of pyclingo: terms, values, pools,
expressions, and comparisons. Operator methods on these classes construct
each other's classes (e.g. X + 1 builds an Expression, X == Y builds a
Comparison), so they are merged into one module to avoid deferred imports.
Everything else in the package imports downward from here.
"""

from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Never, cast, overload

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


# One occurrence of a predicate class: (class, classically negated, is_atom).
#
# The same p(...) syntax plays two grammatical roles in ASP. As an ATOM it is
# a statement with a truth value — a fact, a rule head, a body literal, or an
# element/condition inside an aggregate, choice, or conditional literal. As a
# TERM it is a piece of data sitting inside another predicate's argument, with
# no truth value of its own. In region(cell(1, 2), a), region/2 occurs as an
# atom; cell/2 occurs only as a term. is_atom records which role: #show
# signatures exist only for atom occurrences (a directive for cell/2 here
# would draw gringo's "no atoms over signature" info), while term occurrences
# still matter for reconstructing solutions into typed instances.
type AtomSign = tuple[PREDICATE_CLASS_TYPE, bool, bool]

# Type aliases for the operator cluster
type EXPRESSION_FIELD_TYPE = Value | Expression | int
type VALUE_EXPRESSION_TYPE = Value | Expression


class RenderingContext(Enum):
    """
    Enum for defining rendering contexts where predicates may need to know to surround themselves in parentheses.
    """

    DEFAULT = "default"
    LONE_PREDICATE_ARGUMENT = "lone_predicate_argument"


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

    def collect_predicate_signs(self) -> set[AtomSign]:
        """
        Collects (class, negated, is_atom) occurrences in this term; empty by
        default, composites recurse, Predicate reports itself and demotes its
        argument-position children.
        """
        return set()

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """All Predicate classes used in this term (both signs, any position)."""
        return {predicate for predicate, _negated, _is_atom in self.collect_predicate_signs()}

    @abstractmethod
    def collect_defined_constants(self) -> set[str]:
        """Collects all defined constant names used in this term."""
        pass

    @abstractmethod
    def collect_variables(self) -> set[str]:
        """Collects the names of all variables used in this term."""
        pass

    def freeze(self) -> None:  # noqa: B027 (deliberate no-op default, not a forgotten abstract)
        """
        Called when a Rule captures this term. Mutable builders (Choice,
        Aggregate) lock themselves so later mutation cannot silently rewrite a
        recorded rule; composite terms propagate to their children; everything
        else is already immutable and does nothing.
        """


class BasicTerm(Term, ABC):
    """
    Abstract base class for terms that can be direct predicate arguments.

    This includes values (variables, constants) and predicates themselves.
    BasicTerms are the fundamental building blocks for constructing ASP programs.
    """


class PredicateBase(BasicTerm, ABC):
    """
    Marker base for Predicate, which is defined in predicate.py. It exists so
    code here can recognize predicates with isinstance (e.g. as comparison
    operands): predicate.py imports downward from core, so core cannot import
    the Predicate class itself.
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
    # calling __eq__. LIST/TUPLE membership is a trap: CPython short-circuits on
    # identity, so a PRESENT cached value returns True silently, while an absent
    # one reaches __eq__ and raises via Comparison.__bool__ — it appears to work
    # until the first miss. Use sets for containment.
    __hash__ = object.__hash__

    def __lt__(self, other: Any) -> Comparison:
        if not isinstance(other, (ComparableTerm, PredicateBase, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.LESS_THAN, other)

    def __le__(self, other: Any) -> Comparison:
        if not isinstance(other, (ComparableTerm, PredicateBase, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.LESS_EQUAL, other)

    def __gt__(self, other: Any) -> Comparison:
        if not isinstance(other, (ComparableTerm, PredicateBase, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.GREATER_THAN, other)

    def __ge__(self, other: Any) -> Comparison:
        if not isinstance(other, (ComparableTerm, PredicateBase, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.GREATER_EQUAL, other)

    def __eq__(self, other: Any) -> Comparison:  # type: ignore[override]
        if not isinstance(other, (ComparableTerm, PredicateBase, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.EQUAL, other)

    def __ne__(self, other: Any) -> Comparison:  # type: ignore[override]
        if not isinstance(other, (ComparableTerm, PredicateBase, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, ComparisonOperator.NOT_EQUAL, other)


class AggregateBase(ComparableTerm, ABC):
    """
    Marker base for aggregates (#count, #sum, ...), which are defined in
    aggregates.py. It exists so code here can recognize aggregates with
    isinstance: aggregates.py imports downward from core, so core cannot
    import the Aggregate class itself.
    """


class Negatable(Term, ABC):
    """
    Mixin for terms that can be default-negated: Predicate, Comparison, and
    DefaultNegation itself. Provides ~, which builds "not term". (On Values
    and Expressions, ~ is bitwise complement instead — integers negate
    bitwise, literals negate logically.)
    """

    def __invert__(self) -> DefaultNegation:
        return DefaultNegation(self)


class _ValueMeta(ABCMeta):
    """
    Caches Value instances: constructing the same value twice returns the same
    object. Construction runs before the cache is written, so a value whose
    validation raises is never cached. All concrete Value subclasses take
    exactly one constructor argument; other shapes fall through so __init__
    can raise its own error, and the cache key includes the argument's type so
    equal-but-distinct-type arguments never share an instance.
    """

    def __call__[T](cls: type[T], *args: Any, **kwargs: Any) -> T:
        if len(args) + len(kwargs) == 1:
            value = args[0] if args else next(iter(kwargs.values()))
            key = (cls, type(value), value)
            try:
                cached = Value._cache.get(key)
            except TypeError:
                # Unhashable constructor argument; let __init__ reject it with a clear error
                return super().__call__(*args, **kwargs)  # type: ignore[misc, no-any-return]
            if cached is None:
                cached = super().__call__(*args, **kwargs)  # type: ignore[misc]
                Value._cache[key] = cached
            return cast(T, cached)
        return super().__call__(*args, **kwargs)  # type: ignore[misc, no-any-return]


class Value(BasicTerm, ComparableTerm, ABC, metaclass=_ValueMeta):
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

    @classmethod
    def clear_cache(cls) -> None:
        """
        Empty the value cache (it grows monotonically across a process).

        Values held from before the clear remain valid but are no longer the
        same objects as newly constructed equal values, so avoid mixing them
        in identity-keyed containers like sets across a clear.
        """
        Value._cache.clear()

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

    def __invert__(self) -> Never:
        """~ is reserved for default negation, which needs a literal: always raises."""
        raise TypeError(
            "~ is default negation and applies to literals (predicates, comparisons); "
            "for bitwise complement, use Compl(x)"
        )


class Variable(Value):
    """
    Represents a variable in an ASP program.

    Variables in ASP start with an uppercase letter or can be an underscore '_'
    for anonymous variables. (Deliberately narrower than gringo, which also
    allows _X-style names: one underscore means anonymous, full stop.) During solving a variable ranges over all ground
    terms — numbers, strings, and compound terms alike: X == 4 compares against
    a number, X == Cell(1, 2) against a compound term (and C == Cell(X, ANY)
    destructures a bound compound). For several alternatives at once, use a
    pool: X.in_((Cell(1, 2), Cell(3, 4))).
    """

    def __init__(self, name: str):
        if not name.isascii():
            raise ValueError(f"Variable name must be ASCII (gringo's lexer is ASCII-only): {name!r}")
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

    def collect_defined_constants(self) -> set[str]:
        return set()

    def __repr__(self) -> str:
        return f"Variable({self._name!r})"

    def __str__(self) -> str:
        return self.name

    def collect_variables(self) -> set[str]:
        return {self.name}

    def __getitem__(self, index: int | str) -> Variable:
        """
        A derived variable: X[1] is Variable("X_1") and X["adj"] is
        Variable("X_adj"). Structured naming for code that mints families
        of related variables (a helper building rule fragments derives
        locals from a base it owns, instead of string-suffix plumbing);
        chains naturally (X[1]["lo"] is X_1_lo). The derived name passes
        Variable's own validation, so bad suffixes fail loudly.
        """
        if isinstance(index, bool) or not isinstance(index, (int, str)) or (isinstance(index, int) and index < 0):
            raise TypeError(f"Variable index must be a non-negative int or a str, got {index!r}")
        if index == "":
            raise TypeError("Variable index cannot be an empty string")
        return Variable(f"{self._name}_{index}")

    def in_(self, pool_or_range: Pool | list | tuple | range) -> Comparison:
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
        if not value.isascii():
            raise ValueError(f"Defined constant name must be ASCII (gringo's lexer is ASCII-only): {value!r}")
        if not value or not value[0].islower():
            raise ValueError(f"Defined constant must start with a lowercase letter: {value}")
        if value == "not":
            raise ValueError("'not' is reserved in ASP and cannot be a constant name")

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
    Represents a range pool in ASP programs, like 1..5 or 1..N.

    Bounds must be integer-valued: ints, Numbers, #const-defined constants,
    Variables, or integer Expressions (X = 1..N*2 is fine when N is bound).
    A variable bound must be bound by a positive body literal — ranges never
    invert (gringo rejects deriving N from X = 1..N with X bound), which
    the scoping analysis models as a one-way binding edge. A #const bound is
    trusted to be integer-valued — this class cannot see the program's
    constant table, so a string-valued constant renders fine and fails at
    solve. A range that is empty at runtime (start exceeding end after
    substitution) is not an error: it simply matches nothing.
    """

    def __init__(self, start: int | Value | Expression, end: int | Value | Expression):
        """
        Initialize a range pool with start and end values (both inclusive).

        Raises if either bound is of the wrong type, or if both are literal
        integers with start exceeding end.
        """
        # Convert integers to Number objects
        if isinstance(start, int):
            start = Number(start)
        if isinstance(end, int):
            end = Number(end)

        for label, bound in (("start", start), ("end", end)):
            if isinstance(bound, String):
                raise TypeError(f"Range {label} must be integer-valued, got a String")
            if not isinstance(bound, (Number, DefinedConstant, Variable, Expression)):
                raise TypeError(
                    f"Range {label} must be an int, Number, DefinedConstant, Variable, "
                    f"or Expression, got {type(bound).__name__}"
                )

        if isinstance(start, Number) and isinstance(end, Number) and start.value > end.value:
            raise ValueError(f"Range {start.value}..{end.value} is empty (start exceeds end)")

        self._start: Value | Expression = start
        self._end: Value | Expression = end

    @property
    def start(self) -> Value | Expression:
        """The starting value of the range (inclusive)."""
        return self._start

    @property
    def end(self) -> Value | Expression:
        """The ending value of the range (inclusive)."""
        return self._end

    @property
    def is_grounded(self) -> bool:
        """Grounded when both bounds are (variable bounds ground at solve)."""
        return self._start.is_grounded and self._end.is_grounded

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        return f"{self.start.render()}..{self.end.render()}"

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        constants.update(self.start.collect_defined_constants())
        constants.update(self.end.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        return self.start.collect_variables() | self.end.collect_variables()


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
            elif isinstance(element, Pool):
                raise TypeError("Pools cannot be nested inside pools")
            elif isinstance(element, BasicTerm):
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

    def collect_predicate_signs(self) -> set[AtomSign]:
        # Pool elements sit in argument positions: demote to non-atoms
        return {
            (predicate, negated, False)
            for element in self.elements
            for predicate, negated, _is_atom in element.collect_predicate_signs()
        }


def pool(elements: range | Sequence[int | str | BasicTerm] | Pool) -> Pool:
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

    if isinstance(elements, range):
        if len(elements) == 0:
            raise ValueError("Cannot create an empty pool from an empty range")
        if elements.step == 1:
            return RangePool(Number(elements.start), Number(elements.stop - 1))
        return ExplicitPool([Number(x) for x in elements])

    if isinstance(elements, (list, tuple)):
        if not elements:
            raise ValueError("Cannot create an empty pool")

        pool_elements = []
        for element in elements:
            if isinstance(element, int):
                pool_elements.append(Number(element))
            elif isinstance(element, str):
                pool_elements.append(String(element))
            elif isinstance(element, Pool):
                raise TypeError("Pools cannot be nested inside pools")
            elif isinstance(element, BasicTerm):
                # Ensure the element is grounded
                if not element.is_grounded:
                    raise ValueError(f"Pool elements must be grounded: {element.render()}")
                pool_elements.append(element)
            else:
                raise TypeError(
                    f"Pool elements must be ints, strs, or grounded basic terms, got {type(element).__name__}"
                )

        return ExplicitPool(pool_elements)

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
        if first_term is not None and operator not in BINARY_OPERATIONS:
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
        first_str = self.first_term.render(RenderingContext.DEFAULT, self.operator, False)
        second_str = self.second_term.render(RenderingContext.DEFAULT, self.operator, True)

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

    def __invert__(self) -> Never:
        """~ is reserved for default negation, which needs a literal: always raises."""
        raise TypeError(
            "~ is default negation and applies to literals (predicates, comparisons); "
            "for bitwise complement, use Compl(x)"
        )

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.render()!r})"

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


class Comparison(Negatable):
    """
    Represents a comparison between two terms in an ASP program.

    Comparisons can be equality (=), inequality (!=), or
    relational comparisons (<, <=, >, >=).
    """

    _left_term: ComparableTerm
    _right_term: ComparableTerm | Pool | PredicateBase

    def __init__(
        self,
        left_term: int | str | Term,
        operator: ComparisonOperator,
        right_term: int | str | Term,
    ):
        """
        int and str operands are coerced to Number and String.

        A Pool may only appear on the right, compared by equality against a variable.
        A Predicate (compound term) may appear on the right against a Variable on
        the left — X == Cell(1, 2) binds, C == Cell(X, ANY) destructures; Python's
        reflection normalizes Cell(...) == X to the same shape.
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
        elif isinstance(right_term, (ComparableTerm, Pool, PredicateBase)):
            self._right_term = right_term
        else:
            raise TypeError(
                f"Right term must be an int, str, comparable term (Value, Expression, or Aggregate), "
                f"Pool, or Predicate, got {type(right_term).__name__}"
            )

        if not isinstance(operator, ComparisonOperator):
            raise TypeError(f"Comparison operator must be a ComparisonOperator, got {type(operator).__name__}")
        self._operator = operator

        if isinstance(self._left_term, AggregateBase) and isinstance(self._right_term, AggregateBase):
            raise ValueError(
                "A comparison cannot have aggregates on both sides (clingo syntax error); "
                "bind one aggregate to a variable in a separate rule"
            )

        if isinstance(right_term, Pool) and operator != ComparisonOperator.EQUAL:
            raise ValueError("A pool can only be compared using equality")

        if isinstance(right_term, Pool) and not isinstance(left_term, Variable):
            raise ValueError("A comparison involving a pool must have a variable on the left")

        if isinstance(self._right_term, PredicateBase) and not isinstance(self._left_term, Variable):
            raise ValueError(
                "A comparison with a compound term must have a Variable on the other side: "
                "clingo orders terms by type, so comparing a number or expression against a "
                "compound term is vacuously true or false, never what you meant"
            )

    @property
    def left_term(self) -> ComparableTerm:
        return self._left_term

    @property
    def operator(self) -> ComparisonOperator:
        return self._operator

    @property
    def right_term(self) -> ComparableTerm | Pool | PredicateBase:
        return self._right_term

    def freeze(self) -> None:
        self.left_term.freeze()
        self.right_term.freeze()

    def collect_predicate_signs(self) -> set[AtomSign]:
        signs: set[AtomSign] = set()
        for side in (self.left_term, self.right_term):
            side_signs = side.collect_predicate_signs()
            if isinstance(side, PredicateBase):
                # A predicate used as a comparison operand is a compound TERM
                # (data), not an atom: no show signature of its own
                side_signs = {(predicate, negated, False) for predicate, negated, _ in side_signs}
            signs |= side_signs
        return signs

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

        # Never parenthesized: clingo REJECTS "not (X < 3)" — a comparison
        # after not must be bare, and no other position needs parens either
        return f"{left_str} {self.operator.value} {right_str}"

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

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.render()!r})"

    @property
    def is_equality(self) -> bool:
        """Whether this comparison uses = (the only operator that binds variables)."""
        return self.operator == ComparisonOperator.EQUAL

    def inverse(self) -> Comparison:
        """The complementary comparison: X == N inverts to X != N, X < N to X >= N."""
        if isinstance(self._right_term, Pool):
            raise ValueError(
                "A pool comparison has no inverse: pools expand disjunctively, so "
                "'X != (2;3)' is true for every X. Write the domain restriction as "
                "positive conditions instead."
            )
        return Comparison(self._left_term, self.operator.inverse, self._right_term)

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


class DefaultNegation(Negatable):
    """
    Represents default negation ('not') in ASP programs.

    Default negation expresses that a literal cannot be proven true (it may be
    either false or unknown). It is distinct from classical negation (-p),
    which asserts explicit falsity and lives on the atom itself: unary minus
    on a Predicate instance flips its sign.
    """

    def __init__(self, term: Negatable):
        """
        Initialize a default negation, simplifying nested negations:
        an odd number of negations is equivalent to 'not p', an even number to 'not not p'.
        """
        if not isinstance(term, Negatable):
            raise TypeError("Default negation can only be applied to predicates, comparisons, or already negated terms")

        if isinstance(term, Comparison) and isinstance(term.right_term, Pool):
            raise ValueError(
                "Negating a pool comparison does not mean 'not in': pools expand "
                "disjunctively, so 'not X = (2;3)' is true for every X. Write "
                "separate conditions instead, e.g. X != 2, X != 3"
            )

        # Negating a double negation collapses it: not(not not X) becomes not X,
        # so we store X. Anything else (X or not X) is stored as given.
        self._term: Term = term
        if isinstance(term, DefaultNegation) and isinstance(term.term, DefaultNegation):
            self._term = term.term.term

    @property
    def term(self) -> Term:
        """The term being negated."""
        return self._term

    @property
    def is_grounded(self) -> bool:
        """A negation is grounded if its term is grounded."""
        return self._term.is_grounded

    def collect_defined_constants(self) -> set[str]:
        return self._term.collect_defined_constants()

    def collect_variables(self) -> set[str]:
        return self._term.collect_variables()

    def freeze(self) -> None:
        self._term.freeze()

    def collect_predicate_signs(self) -> set[AtomSign]:
        return self._term.collect_predicate_signs()

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        return f"not {self._term.render()}"

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.render()!r})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Default negation is body-only: raises in heads."""
        if is_in_head:
            raise ValueError("Default negation (not) cannot be used in rule heads")


def Not(term: Negatable) -> DefaultNegation:
    """
    Helper function to create default negation.

    This function applies default negation to the term, with automatic
    simplification of nested negations when appropriate.

    Args:
        term: The term to negate with default negation.

    Returns:
        Term: A default negation of the given term, simplified if needed.

    Example:
        >>> from pyclingo import Predicate
        >>> Person = Predicate.define("person", ["name"])
        >>> person = Person(name="john")
        >>> Not(person).render()
        'not person("john")'
        >>> Not(Not(person)).render()
        'not not person("john")'
        >>> Not(Not(Not(person))).render()  # triple negation simplifies
        'not person("john")'
    """
    return DefaultNegation(term)


def Abs(term: EXPRESSION_FIELD_TYPE) -> Expression:
    """Builds an absolute-value expression, |term|."""
    return Expression(None, Operation.ABS, term)


def Compl(term: EXPRESSION_FIELD_TYPE) -> Expression:
    """
    Builds a bitwise-complement expression, rendered ~term.

    A named function rather than Python's ~ operator: in pyclingo, ~ is
    reserved for default negation on literals, so the two meanings of
    clingo's ~ never share a spelling.
    """
    return Expression(None, Operation.COMPLEMENT, term)


ANY = Variable("_")


class Vars:
    """
    Variables by attribute: V.Cell is Variable("Cell"), no declaration
    needed — the module-level V is ready to use, and attribute access is
    the whole API. Kills the create_variables preamble for authors who
    prefer inline names; Variable name validation still applies (V.cell
    raises with the uppercase rule). Combines with indexing: V.C[1] is
    Variable("C_1").
    """

    def __getattr__(self, name: str) -> Variable:
        return Variable(name)


V = Vars()


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
