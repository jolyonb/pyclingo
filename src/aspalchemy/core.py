"""
The mutually-recursive operator cluster of aspalchemy: terms, values, pools,
expressions, and comparisons. Operator methods on these classes construct
each other's classes (e.g. X + 1 builds an Expression, X == Y builds a
Comparison), so they are merged into one module to avoid deferred imports.
Everything else in the package imports downward from here.
"""

import threading
import weakref
from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Never, Self, TypeIs, cast, overload

from aspalchemy.operators import (
    BINARY_OPERATIONS,
    EXPLICIT_PARENS_OPERATIONS,
    INVOLUTION_OPERATIONS,
    NONCOMMUTATIVE_OPERATIONS,
    PRECEDENCE,
    UNARY_OPERATIONS,
    ComparisonOperator,
    Operation,
)

if TYPE_CHECKING:
    # Annotation-only upward reference (scoping.py holds another):
    # collect_predicates returns predicate classes, but core cannot import
    # predicate at runtime
    from aspalchemy.predicate import Predicate


# One occurrence of a predicate class: (class, classically negated, is_atom).
# is_atom marks whether it occurs as an atom (a statement, which can be true
# or false) or as an argument (data nested inside another predicate);
# Term.collect_predicate_occurrences decides that role.
type PredicateOccurrence = tuple[type[Predicate], bool, bool]

# Type aliases for the operator cluster
type ExpressionFieldType = Value | Expression | int
type ValueExpressionType = Value | Expression


def require_int32(value: int, noun: str, extra: str = "") -> None:
    """
    Reject ints outside clingo's 32-bit range, which clingo silently wraps.
    One home for the bounds; noun and extra tailor the message to each
    caller. (Tests pin short fragments of these messages, not full text —
    the wording is not API.)
    """
    if not -(2**31) <= value < 2**31:
        raise ValueError(
            f"{noun} {value} is outside clingo's integer range [-2147483648, 2147483647]; "
            f"clingo would silently wrap it{extra}"
        )


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

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        """
        Collect (class, negated, is_atom) occurrences of predicate classes in
        this node. Every predicate occurrence is one of two things: an ATOM —
        a statement that can be true or false (a fact, rule head, body literal,
        or an aggregate/choice/conditional-literal condition), which gets a
        #show signature — or an ARGUMENT: a predicate sitting in a data slot
        inside another, just a value with no truth of its own. The same class
        can be either, depending on where it sits: in region(cell(1, 2)),
        region is an atom and cell is an argument.

        A node cannot know its own role: whether cell(1, 2) is a statement or
        an argument depends entirely on what encloses it. So the caller states
        it, in as_argument — the slot the PARENT places this node in. It starts
        False at a top-level statement and, once you descend into a data slot,
        turns True and stays True (an argument's contents are arguments too);
        it never turns back off. Three kinds of edge:

        - The boundary starts it False (a segment's statements, a show_when
          condition): those stand where statements stand, not in a data slot.
        - An argument edge forces True — a predicate's own arguments, pool
          elements, aggregate/weak/optimization tuple terms, a predicate
          operand of a comparison. Everything nested below stays an argument.
        - Every other edge passes as_argument through unchanged (a conditional
          literal, a choice element, an aggregate's conditions, default
          negation): these do not change whether their content is a statement.

        Only Predicate reads as_argument, recording is_atom = not as_argument;
        every other node is plumbing that routes the slot to its children.
        Leaves (values, constants) contain no predicates and report nothing.
        """
        return set()

    def collect_predicates(self) -> set[type[Predicate]]:
        """All Predicate classes used in this term."""
        return {predicate for predicate, _negated, _is_atom in self.collect_predicate_occurrences(as_argument=False)}

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

    def _comparison(self, operator: ComparisonOperator, other: Any) -> Comparison:
        """The shared operand guard: one home for the teaching on each rejected shape."""
        if isinstance(other, Pool):
            raise ValueError(
                f"Cannot compare {type(self).__name__} with a pool: pools expand "
                f"disjunctively, which comparison operators cannot express. For domain "
                f"membership use X.in_((1, 2))."
            )
        if isinstance(other, type) and issubclass(other, PredicateBase):
            raise ValueError(
                f"Cannot compare {type(self).__name__} with the predicate class "
                f"{other.__name__} — compare against an instance: {other.__name__}(...)"
            )
        if not isinstance(other, (ComparableTerm, PredicateBase, int, str)):
            raise ValueError(f"Cannot compare {type(self).__name__} with {type(other).__name__}")
        return Comparison(self, operator, other)

    def __lt__(self, other: Any) -> Comparison:
        return self._comparison(ComparisonOperator.LESS_THAN, other)

    def __le__(self, other: Any) -> Comparison:
        return self._comparison(ComparisonOperator.LESS_EQUAL, other)

    def __gt__(self, other: Any) -> Comparison:
        return self._comparison(ComparisonOperator.GREATER_THAN, other)

    def __ge__(self, other: Any) -> Comparison:
        return self._comparison(ComparisonOperator.GREATER_EQUAL, other)

    def __eq__(self, other: Any) -> Comparison:  # type: ignore[override]
        return self._comparison(ComparisonOperator.EQUAL, other)

    def __ne__(self, other: Any) -> Comparison:  # type: ignore[override]
        return self._comparison(ComparisonOperator.NOT_EQUAL, other)


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
    DefaultNegation itself. Provides ~, which builds "not term" — except on
    plain comparisons, where ~ and Not() build the COMPLEMENTARY comparison
    instead (see Not). (On Values and Expressions, ~ raises a teaching
    error: bitwise complement is spelled Compl(x).)
    """

    @abstractmethod
    def __invert__(self) -> DefaultNegation | Comparison:
        """~term: "not term" for atoms and negations; the COMPLEMENT for plain comparisons (see Not)."""


class ArithmeticOps:
    """
    The arithmetic operator suite shared by Value and Expression: every
    operator builds an Expression (or raises its teaching error). One home —
    the two classes accept the same operand union. self is typed Any because
    a mixin cannot name its hosts' union; the only inheritors are Value and
    Expression, exactly the types Expression's operands accept.
    """

    def __add__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.ADD, other)

    def __radd__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.ADD, self)

    def __sub__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.SUBTRACT, other)

    def __rsub__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.SUBTRACT, self)

    def __mul__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.MULTIPLY, other)

    def __rmul__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.MULTIPLY, self)

    def __neg__(self: Any) -> ValueExpressionType:
        """Unary minus is an involution in clingo, so -(-x) IS x — not an Expression over one."""
        return Expression(None, Operation.UNARY_MINUS, self)

    def __floordiv__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.INTEGER_DIVIDE, other)

    def __rfloordiv__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.INTEGER_DIVIDE, self)

    def __truediv__(self, other: object) -> Never:
        raise TypeError(
            "clingo has no true division; use // (renders as ASP '/', integer division truncating toward zero)"
        )

    def __rtruediv__(self, other: object) -> Never:
        raise TypeError(
            "clingo has no true division; use // (renders as ASP '/', integer division truncating toward zero)"
        )

    def __mod__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.MODULO, other)

    def __rmod__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.MODULO, self)

    def __pow__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.POWER, other)

    def __rpow__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.POWER, self)

    def __and__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.BITAND, other)

    def __rand__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.BITAND, self)

    def __or__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.BITOR, other)

    def __ror__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.BITOR, self)

    def __xor__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(self, Operation.BITXOR, other)

    def __rxor__(self: Any, other: ExpressionFieldType) -> Expression:
        return Expression(other, Operation.BITXOR, self)

    def __invert__(self) -> Never:
        """~ is reserved for default negation, which needs a literal: always raises."""
        raise TypeError(
            "~ is default negation and applies to literals (predicates, comparisons); "
            "for bitwise complement, use Compl(x)"
        )

    def __abs__(self: Any) -> Expression:
        """
        abs(x) is |x| — unambiguous, unlike ~ (which stays reserved for negation).
        Idempotent: abs(abs(x)) is abs(x), one node, not two.
        """
        return Expression(None, Operation.ABS, self)


class _ValueMeta(ABCMeta):
    """
    Caches Value instances: constructing the same value twice returns the same
    object for as long as the first lives. The cache holds its entries weakly,
    so values nothing references anymore are evicted with their keys — a
    long-running generator does not accumulate dead values. Construction runs
    before the cache is written, so a value whose validation raises is never
    cached.

    Only plain values enter the cache. The argument converts to its natural
    plain form first — str/int subclasses exactly as construction stores
    them, so what is keyed is what is stored, and equal-after-conversion
    inputs share one canonical instance. After conversion, every valid
    one-argument Value holds exactly a plain str or a plain int; those key
    as (class, value), unambiguous because str and int never compare equal.
    Every other shape — bool, float, an unhashable, no argument at all —
    never touches the cache and falls through: __init__ rejects the wrong
    shapes, and zero-argument Supremum/Infimum are owned by their own
    __new__ (strongly, surviving clear_cache()).
    """

    def __call__[T](cls: type[T], *args: Any, **kwargs: Any) -> T:
        # Value constructors are positional-only, so any keyword call falls
        # through for __init__ to reject natively — nothing to launder
        if not kwargs and len(args) == 1:
            value = args[0]
            if isinstance(value, str):
                # Handle subclasses
                value = str(value)
                args = (value,)
            elif isinstance(value, int) and not isinstance(value, bool):
                value = int(value)
                args = (value,)
            if type(value) in (str, int):
                key = (cls, value)
                cached = Value._cache.get(key)
                if cached is None:
                    # Double-checked under the lock: two racing constructors
                    # must agree on ONE canonical object — identity hashing
                    # rests on every live equal value being that object.
                    # Hits stay lock-free.
                    with Value._cache_lock:
                        cached = Value._cache.get(key)
                        if cached is None:
                            cached = super().__call__(*args, **kwargs)  # type: ignore[misc]
                            Value._cache[key] = cached
                return cast(T, cached)
        return super().__call__(*args, **kwargs)  # type: ignore[misc, no-any-return]


class Value(BasicTerm, ComparableTerm, ArithmeticOps, ABC, metaclass=_ValueMeta):
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
    The cache is weak (dead values are evicted, not hoarded); copy/deepcopy
    return the object itself, and unpickling re-interns through this cache,
    so the guarantee survives copying and pickling alike. (See "Copying,
    Pickling, and Identity" in src/aspalchemy/CLAUDE.md for the whole story.)
    """

    _cache: ClassVar[weakref.WeakValueDictionary[tuple[type, Any], Value]] = weakref.WeakValueDictionary()
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def clear_cache(cls) -> None:
        """
        Empty the value cache. Rarely needed: entries whose values are no
        longer referenced anywhere are evicted automatically.

        Values held from before the clear remain valid but are no longer the
        same objects as newly constructed equal values, so avoid mixing them
        in identity-keyed containers like sets across a clear.
        """
        Value._cache.clear()

    def __copy__(self) -> Self:
        """Values are immutable and interned: the copy IS the original."""
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """
        Values are immutable and interned: the deep copy IS the original. A
        distinct copy would be equal-but-not-identical to the cache resident,
        breaking the same-object guarantee identity hashing rests on.
        """
        return self

    def __reduce__(self) -> tuple[type[Value], tuple[Any, ...]]:
        """
        Pickle as "call the class with the stored value": unpickling routes
        through the interning metaclass, so the loaded object IS the
        canonical resident and the identity guarantees survive the round
        trip. Concrete Values hold exactly their constructor argument
        (Supremum/Infimum hold nothing, and their __new__ returns the
        singleton), so the instance dict is the argument list. copy and
        deepcopy never reach this hook — __copy__/__deepcopy__ above return
        self directly.
        """
        return (type(self), tuple(self.__dict__.values()))

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

    def __init__(self, name: str, /):
        if not isinstance(name, str):
            raise TypeError(f"Variable name must be a string, got {type(name).__name__}")
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
        Variable's own validation, so bad suffixes fail loudly. The empty
        string is the identity — X[""] is X — so an optional suffix needs
        no special-casing.
        """
        if isinstance(index, bool) or not isinstance(index, (int, str)) or (isinstance(index, int) and index < 0):
            raise TypeError(f"Variable index must be a non-negative int or a str, got {index!r}")
        if index == "":
            return self
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
            >>> from aspalchemy import RangePool
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

    def __init__(self, value: int, /):
        # bool subclasses int, and a boolean is never a valid ASP term
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Number value must be an integer, got {type(value).__name__}")
        # value is a plain int here: _ValueMeta.__call__ normalizes subclass
        # instances before construction (what is keyed is what is stored)
        require_int32(value, "Number value")
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

    def __init__(self, value: str, /):
        """No double quotes, backslashes, or newlines (no escaping support); single quotes are fine."""
        if not isinstance(value, str):
            raise TypeError(f"String constant value must be a string, got {type(value).__name__}")
        # value is a plain str here: _ValueMeta.__call__ normalizes subclass
        # instances before construction (what is keyed is what is stored)
        if '"' in value:
            raise ValueError(f"String constant cannot contain double quotes (no escaping support): {value}")
        if "\\" in value or "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError(
                f"String constant cannot contain backslashes, newlines, or NUL "
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

    def __init__(self, value: str, /):
        """value is the constant's name: lowercase first letter, then letters, digits, and underscores."""
        if not isinstance(value, str):
            raise TypeError(f"Defined constant name must be a string, got {type(value).__name__}")
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


class ExtremeConstant(ConstantBase, ABC):
    """
    clingo's ordering end markers, #sup and #inf: every ground term sorts
    strictly between them. They arise naturally as the value of a
    #min/#max aggregate over an EMPTY set (the min of nothing is #sup,
    the max of nothing is #inf), so a solution atom can carry one — and a
    comparison against it asks "was the set empty": M == SUP. Ordinary
    comparable values otherwise; SUP and INF are the two instances —
    true singletons (Supremum() is SUP even across a clear_cache(),
    which ordinary interned values do not promise). No arithmetic: like
    Strings, #sup/#inf in an expression is undefined for every program.
    """

    _TEXT: ClassVar[str]
    # One instance per concrete class, held strongly: unlike the weak value
    # cache, a singleton's identity must survive clear_cache()
    _instances: ClassVar[dict[type, ExtremeConstant]] = {}

    def __new__(cls) -> Self:
        instance = cls._instances.get(cls)
        if instance is None:
            # Under the cache lock: an unlocked check-then-set could mint two
            # "singletons" for a user subclass first instantiated concurrently
            # (SUP/INF themselves are created at import, before user threads)
            with Value._cache_lock:
                instance = cls._instances.get(cls)
                if instance is None:
                    instance = super().__new__(cls)
                    cls._instances[cls] = instance
        return cast(Self, instance)

    def render(
        self,
        context: RenderingContext = RenderingContext.DEFAULT,
        parent_op: Operation | None = None,
        is_right_operand: bool = False,
    ) -> str:
        return self._TEXT

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def __str__(self) -> str:
        return self._TEXT


class Supremum(ExtremeConstant):
    """#sup, the greatest term of clingo's ordering; SUP is the instance."""

    _TEXT = "#sup"


class Infimum(ExtremeConstant):
    """#inf, the least term of clingo's ordering; INF is the instance."""

    _TEXT = "#inf"


SUP = Supremum()
INF = Infimum()


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
        raise ValueError(
            "Pools can only be used as arguments to predicates or in comparisons. "
            "For a disjunctive head (a ; b), aspalchemy has no construct: "
            "A Choice with at_least(1) covers most uses, raw_asp() the rest."
        )


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
            if "_" in bound.collect_variables():
                raise ValueError(
                    f"'_' cannot appear in a range {label}: it matches anything and "
                    f"binds nothing, so gringo rejects the rule as unsafe. Use a "
                    f"named variable bound by a positive condition."
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

    def __repr__(self) -> str:
        """RangePool(1, 5) — reconstructable; Number bounds show as plain ints."""
        start = self._start.value if isinstance(self._start, Number) else self._start
        end = self._end.value if isinstance(self._end, Number) else self._end
        return f"RangePool({start!r}, {end!r})"

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        constants.update(self.start.collect_defined_constants())
        constants.update(self.end.collect_defined_constants())

        return constants

    def collect_variables(self) -> set[str]:
        return self.start.collect_variables() | self.end.collect_variables()


class ExplicitPool(Pool):
    """
    Represents an explicit pool in ASP programs, like (1;2;3) or (X-1;X+1).

    Elements are basic terms and expressions; ints and strs coerce. An
    UNGROUNDED pool (variables/expressions in elements) is legal only in
    rule-HEAD arguments, where gringo expands it conjunctively —
    adj(X, (X-1; X+1)) derives both neighbor atoms. Everywhere else
    (bodies, choice elements, conditions, comparisons) ungrounded pools
    are rejected at rule assembly: gringo judges each expanded copy
    separately for safety there, which aspalchemy does not model. Note the
    per-slot shape: correlated argument-TUPLE pools like p(1,2; 3,4)
    do not factor into slot pools and stay raw_asp territory.
    """

    def __init__(self, elements: Sequence[int | str | BasicTerm | Expression]):
        """
        Initialize an explicit pool from a non-empty sequence of elements;
        ints and strs are coerced to Number and String.

        Raises if any element is of an unsupported type.
        """
        if isinstance(elements, str):
            raise TypeError(
                'A bare string is a sequence of characters: ExplicitPool("abc") would '
                'become ("a"; "b"; "c"). Pass a list — ExplicitPool(["abc"]) — for a '
                "one-string pool."
            )
        # Materialize BEFORE the emptiness check: an iterator is always
        # truthy, so an empty generator would sail past the check and render
        # p() — gringo's arity-0 atom, a silently different predicate
        elements = list(elements)
        if not elements:
            raise ValueError("Cannot create an empty pool")

        self._elements = []

        for element in elements:
            if isinstance(element, str):
                element = String(element)
            elif isinstance(element, int):
                element = Number(element)
            elif isinstance(element, Pool):
                raise TypeError("Pools cannot be nested inside pools")
            elif not isinstance(element, (BasicTerm, Expression)):
                raise TypeError(
                    f"Pool elements must be ints, strs, basic terms, or expressions, got {type(element).__name__}"
                )

            self._elements.append(element)

        # Depth rides through pools so Predicate's nesting cap sees the
        # Predicate <-> pool alternation (pool(p(pool(...))) chains would
        # otherwise evade MAX_DEPTH and die as a raw RecursionError mid-walk)
        self._depth = 1 + max((getattr(element, "_depth", 0) for element in self._elements), default=0)

    @property
    def elements(self) -> list[BasicTerm | Expression]:
        """The elements of the pool (a defensive copy)."""
        return self._elements.copy()

    @property
    def is_grounded(self) -> bool:
        """Whether every element is grounded; ungrounded pools are legal in rule-head arguments only."""
        return all(element.is_grounded for element in self._elements)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        """Renders as e.g. "(1; 3; 5)"; parentheses are dropped as a lone predicate argument."""
        elements_str = "; ".join(element.render() for element in self._elements)
        return elements_str if context == RenderingContext.LONE_PREDICATE_ARGUMENT else f"({elements_str})"

    def __repr__(self) -> str:
        """ExplicitPool([1, 3, 5]) — reconstructable; Number/String elements show as plain values."""
        plain = [e.value if isinstance(e, (Number, String)) else e for e in self._elements]
        return f"ExplicitPool({plain!r})"

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

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        # Pool elements are always arguments (a pool is a predicate's data), never atoms
        occurrences: set[PredicateOccurrence] = set()
        for element in self.elements:
            occurrences.update(element.collect_predicate_occurrences(as_argument=True))
        return occurrences


def pool(elements: range | Sequence[int | str | BasicTerm | Expression] | Pool) -> Pool:
    """
    Create a Pool object from a general variety of input options.

    Args:
        elements: A Pool object, range, or sequence of elements (integers,
                 strings, basic terms, or expressions — ungrounded elements
                 are legal in rule-head arguments only; see ExplicitPool)

    Returns:
        An appropriate Pool object (RangePool for continuous ranges, ExplicitPool otherwise)

    Note the reading of a pool under negation: gringo expands a pool in a
    negated atom by duplicating the RULE per element, so not p((1; 2))
    means "not p(1) AND not p(2)" — not-EACH, never "not in {1, 2}".

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
    if isinstance(elements, Pool):
        return elements

    if isinstance(elements, range):
        if len(elements) == 0:
            raise ValueError("Cannot create an empty pool from an empty range")
        if elements.step == 1:
            return RangePool(Number(elements.start), Number(elements.stop - 1))
        return ExplicitPool([Number(x) for x in elements])

    if isinstance(elements, (list, tuple)):
        # ExplicitPool validates and coerces every element itself, empty included
        return ExplicitPool(elements)

    raise TypeError(f"Expected Pool, list, tuple, or range, got {type(elements).__name__}")


class _ExpressionMeta(ABCMeta):
    """
    Collapses a doubled involution at the class call: -(-t) IS t and
    Compl(Compl(t)) IS t, so the class call hands back the inner term
    itself — a Variable, a Number, whatever t was — instead of wrapping it
    in two nodes that render as noise. __init__ cannot do this (it cannot
    return a different object), and this is the same hook _ValueMeta already
    uses to intercept its own class call, so both construction paths — the
    Python operators (-X, Compl(x)) and the raw Expression(None, op, e)
    constructor — go through the one door.

    No fixpoint loop is needed: this hook is the only way an Expression is
    built, so no operand reaching it is itself a doubled involution. One
    unwrap is therefore complete, and -(-(-X)) settles at -X.

    Costs, stated rather than hidden. The overloads make the involutions'
    honest return type visible — -X and Compl(x) are Value | Expression, and
    Expression(None, Operation.UNARY_MINUS, e) may hand back a Value — but
    only to a checker that models metaclass __call__. Pyright does (and so
    catches .operator on that raw result); mypy does not, and reads the raw
    path off __init__ as Expression. Both run in the gauntlet, so the
    stricter one holds the line. The overloads also pair each operator
    arity with its operand shape, which means a raw call whose Operation is
    not statically known no longer type-checks; construct such a term
    through the operators, or cast.
    """

    @overload
    def __call__(
        cls,
        first_term: None,
        operator: Literal[Operation.UNARY_MINUS, Operation.COMPLEMENT],
        second_term: ExpressionFieldType,
    ) -> ValueExpressionType: ...

    @overload
    def __call__(
        cls,
        first_term: None,
        operator: Literal[Operation.ABS],
        second_term: ExpressionFieldType,
    ) -> Expression: ...

    @overload
    def __call__(
        cls,
        first_term: ExpressionFieldType,
        operator: Operation,
        second_term: ExpressionFieldType,
    ) -> Expression: ...

    def __call__(
        cls,
        first_term: ExpressionFieldType | None,
        operator: Operation,
        second_term: ExpressionFieldType,
    ) -> ValueExpressionType:
        if (
            first_term is None
            and operator in INVOLUTION_OPERATIONS
            and isinstance(second_term, Expression)
            and second_term.operator is operator
        ):
            return second_term.second_term
        return cast(Expression, super().__call__(first_term, operator, second_term))


class Expression(ComparableTerm, ArithmeticOps, metaclass=_ExpressionMeta):
    """
    Represents a mathematical expression in an ASP program.

    Expressions can be binary operations (e.g., X+Y, X*Z) or
    unary operations (e.g., -X).

    An additive operation with a negative right operand is NORMALIZED at
    construction: X + Number(-1) becomes X - 1, and X - (-Y) becomes X + Y
    (repeated to a fixpoint, so X + (-Number(-1)) is X + 1). Both spellings
    are valid ASP; the fold is cosmetic, and value-preserving. Like Not() on
    a plain comparison, the normalization is visible: the node built as ADD
    reports SUBTRACT from .operator, and .second_term holds the folded term.

    A doubled unary operator is normalized the same way, everywhere it
    occurs rather than only under an additive parent: the two involutions
    collapse to the inner term at the class call (see _ExpressionMeta, so
    -(-X) IS X, not an Expression), and abs, being idempotent, keeps its
    node and adopts the inner operand (abs(abs(X)) is abs(X)). Default
    negation is the deliberate contrast: not not p is PRESERVED, because it
    is not an involution on literals.
    """

    # Nesting cap: the tree walkers (rendering, scoping, collection) recurse
    # per level, and Python's default frame limit kills a ~1000-level chain
    # with a raw RecursionError mid-walk — nearer 500 when a test harness
    # wraps render(). Capping construction at half the worst case turns it
    # into a teaching error on the accumulation line.
    MAX_DEPTH = 250

    # Nesting depth of this node: 1 + its deepest Expression operand
    _depth: int

    def __init__(
        self,
        first_term: ExpressionFieldType | None,
        operator: Operation,
        second_term: ExpressionFieldType,
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
        # clingo arithmetic over strings is undefined for EVERY program, so
        # this is rejectable with certainty here — which also closes the
        # String-inside-an-Expression bypass of the cardinality, weight, and
        # range checks. DefinedConstant stays accepted: its value is
        # unknowable at construction.
        for operand in (first_term, second_term):
            if isinstance(operand, String):
                raise TypeError(
                    f"Strings have no arithmetic in clingo ({operand.render()} in an "
                    f"expression is undefined for every program). Compute with integers, "
                    f"or use a #const via define_constant() for a named value."
                )
            if isinstance(operand, ExtremeConstant):
                raise TypeError(
                    f"{operand.render()} has no arithmetic in clingo: #sup/#inf are the "
                    f"ordering's end markers, defined for comparison only."
                )

        # Convert Python literals to ASP values
        self._first_term = None if first_term is None else self._convert_if_needed(first_term)
        self._operator = operator
        self._second_term = self._convert_if_needed(second_term)

        # Fold a negative right operand into the additive operator (X + -1 is
        # X - 1; X - (-Y) is X + Y), repeating until stable. INT32_MIN is the
        # one Number that cannot fold: its negation is outside clingo's integer
        # range, so there is no Number to fold it to — "X + -2147483648" is
        # legal ASP and stays as written.
        while self._operator in (Operation.ADD, Operation.SUBTRACT):
            second = self._second_term
            if isinstance(second, Number) and -(2**31) < second.value < 0:
                self._second_term = Number(-second.value)
            elif isinstance(second, Expression) and second.operator is Operation.UNARY_MINUS:
                self._second_term = second.second_term
            else:
                break
            self._operator = Operation.SUBTRACT if self._operator is Operation.ADD else Operation.ADD

        # abs is idempotent, not an involution: ||X|| is |X|, so the outer node
        # survives and simply adopts the inner operand. (The involutions collapse
        # to the inner term itself, which only the class call can do: _ExpressionMeta.)
        inner = self._second_term
        if self._operator is Operation.ABS and isinstance(inner, Expression) and inner.operator is Operation.ABS:
            self._second_term = inner.second_term

        # Depth is measured after the folds: unwrapping an operand makes the tree shallower
        self._depth = 1 + max(
            (term._depth for term in (self._first_term, self._second_term) if isinstance(term, Expression)),
            default=0,
        )
        if self._depth > self.MAX_DEPTH:
            raise ValueError(
                f"This expression nests more than {self.MAX_DEPTH} operators deep — almost "
                f"certainly accumulated in a loop (total = total + ...). Deeper chains overflow "
                f"Python's recursion inside the tree walkers; express the accumulation as an "
                f"aggregate instead (e.g. Sum over a predicate holding the addends)."
            )

    @staticmethod
    def _convert_if_needed(value: ExpressionFieldType) -> ValueExpressionType:
        """Coerces Python ints to Number; Values and Expressions pass through."""
        if isinstance(value, (Value, Expression)):
            return value
        # Only int remains: __init__ rejects every other operand shape before this runs
        return Number(value)

    @property
    def first_term(self) -> Value | Expression | None:
        """The left term; None for unary operations."""
        return self._first_term

    @property
    def operator(self) -> Operation:
        return self._operator

    @property
    def second_term(self) -> Value | Expression:
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


def negated_literal_value(term: object) -> int | None:
    """
    The integer behind the one constant-negative spelling -Number(k): a
    unary-minus Expression over a literal Number. None for every other
    shape — general expressions are deliberately not evaluated (the sign
    guards catch the literal spelling; gringo owns the rest).
    """
    if (
        isinstance(term, Expression)
        and term.is_unary
        and term.operator is Operation.UNARY_MINUS
        and isinstance(term.second_term, Number)
    ):
        return -term.second_term.value
    return None


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

        # A bare ANY as a whole side matches anything and binds nothing:
        # gringo makes every such comparison unsafe (each '_' is a fresh
        # unbound variable). ANY inside a compound operand stays legal —
        # C == Cell(X, ANY) destructures.
        for side in (self._left_term, self._right_term):
            if isinstance(side, Variable) and side.is_anonymous:
                raise ValueError(
                    "'_' cannot be a comparison operand: it matches anything and "
                    "binds nothing, so gringo rejects the rule as unsafe. Compare "
                    "against a named variable, or drop the condition."
                )

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
    def right_term(self) -> ComparableTerm | Pool | Predicate:
        # The public annotation says Predicate: PredicateBase is the
        # internal import-DAG marker, and the constructor admits nothing
        # else under it
        return cast("ComparableTerm | Pool | Predicate", self._right_term)

    def freeze(self) -> None:
        self.left_term.freeze()
        self.right_term.freeze()

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        # A predicate operand is data (a compound value), so its edge forces
        # as_argument True. An aggregate operand is different: it evaluates to
        # a value, but its own conditions are atoms — so the edge passes
        # as_argument through, letting the aggregate place its conditions as
        # atoms and its tuple terms as arguments. See
        # Term.collect_predicate_occurrences.
        occurrences: set[PredicateOccurrence] = set()
        for side in (self.left_term, self.right_term):
            child_as_argument = True if isinstance(side, PredicateBase) else as_argument
            occurrences |= side.collect_predicate_occurrences(as_argument=child_as_argument)
        return occurrences

    def __bool__(self) -> bool:
        """
        Comparisons deliberately have no truth value.

        Operators like == on aspalchemy terms build ASP comparison terms rather than
        evaluating anything, so code like `if x == y:` is almost certainly a bug —
        and a chained comparison (X < Y < Z) needs a truth value halfway through,
        because Python evaluates it as (X < Y) and (Y < Z). Raising here turns
        both silent wrongnesses into a loud error.
        """
        raise TypeError(
            f"A Comparison ({self.render()}) has no boolean value: comparison operators on "
            "aspalchemy terms build ASP terms rather than evaluating them. A chained "
            "comparison like X < Y < Z lands here because Python evaluates it as "
            "(X < Y) and (Y < Z) — pass each comparison separately instead: "
            "when(X < Y, Y < Z). If you meant to compare Python objects, compare "
            "their .render() output or use 'is'."
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
        Pool comparisons are body-only too: a pool in a HEAD expands
        conjunctively, so the head would force equality with every pool
        element at once — false whenever the pool has two distinct elements,
        making the program silently unsatisfiable.
        """
        if is_in_head and any(isinstance(term, AggregateBase) for term in (self._left_term, self._right_term)):
            raise ValueError(
                "Comparisons involving aggregates cannot be rule heads; "
                "compute the aggregate in a body condition instead"
            )
        # Right side only: the constructor already rejects a Pool as the
        # LEFT operand (Pool is not a ComparableTerm)
        if is_in_head and isinstance(self._right_term, Pool):
            raise ValueError(
                "A pool comparison cannot be a rule head: head pools expand "
                "conjunctively, so 'X = (1; 2)' forces X to equal every element "
                "at once — false for every X, and the program is silently "
                "unsatisfiable. State the domain restriction in the body instead: "
                "when(X.in_(...), ...)."
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

    def __invert__(self) -> Comparison | DefaultNegation:
        """~comparison builds the complement (X < 5 becomes X >= 5); an aggregate comparison wraps in "not" instead."""
        return Not(self)

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


def _is_plain_comparison(term: Term) -> TypeIs[Comparison]:
    """
    A Comparison with no aggregate side: the one shape Not()/~ normalize to
    its complement and DefaultNegation therefore refuses to wrap. The guard
    and the router share this definition so they can never disagree.
    """
    return isinstance(term, Comparison) and not any(
        isinstance(side, AggregateBase) for side in (term.left_term, term.right_term)
    )


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

        if _is_plain_comparison(term):
            raise ValueError(
                "A plain comparison never wraps in 'not': gringo normalizes "
                "'not X != Y' to the complementary comparison 'X = Y' before "
                "evaluating, and aspalchemy builds that complement directly — "
                "Not(comparison) and ~comparison return it. (Comparisons over "
                "aggregates DO wrap: negated aggregate literals are not "
                "complement-flippable.)"
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

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        return self._term.collect_predicate_occurrences(as_argument=as_argument)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        return f"not {self._term.render()}"

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.render()!r})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Default negation is body-only: raises in heads."""
        if is_in_head:
            raise ValueError(
                "aspalchemy does not model negated heads: gringo itself rewrites "
                "'not p :- body' into a constraint before grounding — nothing is "
                "derived. Spell the constraint directly: forbid(*body, p) (or "
                "when(*body).forbid(p))."
            )

    def __invert__(self) -> DefaultNegation:
        """~ on a negation negates again: a double survives, a triple collapses to a single (see DefaultNegation)."""
        return DefaultNegation(self)


def Not(term: Negatable) -> DefaultNegation | Comparison:
    """
    Default negation — with plain comparisons normalized to their complement.

    On predicates (and negations of them), builds "not term", preserving a
    double negation and collapsing a triple: "not not p" is NOT equivalent
    to p under stable-model semantics (p may support itself through it),
    while "not not not p" is strongly equivalent to "not p".

    On a PLAIN comparison, returns the complementary comparison instead of
    wrapping: gringo itself normalizes "not X != Y" to the binding equality
    "X = Y" before evaluating, so aspalchemy performs the same normalization at
    construction, where the result is visible, safe to bind through, and
    analyzable. Doubles compose: Not(Not(cmp)) is cmp. A comparison CARRYING
    AN AGGREGATE keeps the "not" wrapper — a negated aggregate literal is not
    complement-flippable under stable-model semantics.

    Args:
        term: The term to negate with default negation.

    Example:
        >>> from aspalchemy import Predicate, Variable
        >>> Person = Predicate.define("person", ["name"])
        >>> person = Person(name="john")
        >>> Not(person).render()
        'not person("john")'
        >>> Not(Not(person)).render()
        'not not person("john")'
        >>> Not(Not(Not(person))).render()  # triple negation simplifies
        'not person("john")'
        >>> X = Variable("X")
        >>> Not(X != 5).render()  # a plain comparison inverts
        'X = 5'
    """
    if _is_plain_comparison(term):
        if isinstance(term.right_term, Pool):
            raise ValueError(
                "Negating a pool comparison does not mean 'not in': pools expand "
                "disjunctively, so 'not X = (2;3)' is true for every X. Write "
                "separate conditions instead, e.g. X != 2, X != 3"
            )
        return term.inverse()
    return DefaultNegation(term)


def Compl(term: Value | Expression | int) -> Value | Expression:
    """
    Builds a bitwise-complement expression, rendered ~term.

    A named function rather than Python's ~ operator: in aspalchemy, ~ is
    reserved for default negation on literals, so the two meanings of
    clingo's ~ never share a spelling.

    Bitwise complement is an involution, so Compl(Compl(x)) IS x: the doubled
    form collapses back to the term itself, which is why the return type is
    not just Expression.
    """
    return Expression(None, Operation.COMPLEMENT, term)


ANY = Variable("_")


class Vars:
    """
    Variables by attribute: V.Cell is Variable("Cell"), no declaration
    needed — the module-level V is ready to use, and attribute access is
    the whole API, killing the declare-your-variables preamble for authors
    who prefer inline names; Variable name validation still applies (V.cell
    raises with the uppercase rule). Combines with indexing: V.C[1] is
    Variable("C_1").
    """

    def __getattr__(self, name: str) -> Variable:
        # Python protocol probes (__deepcopy__, IPython's display canary)
        # must signal absence — hasattr and copy only swallow AttributeError
        if name.startswith("_"):
            raise AttributeError(name)
        return Variable(name)


V = Vars()
