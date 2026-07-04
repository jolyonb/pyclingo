from __future__ import annotations

from abc import ABC
from dataclasses import Field, dataclass, fields, make_dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Type, Union

from pyclingo.core import (
    BasicTerm,
    Comparison,
    Expression,
    Number,
    Pool,
    RenderingContext,
    String,
    Term,
    Value,
)

if TYPE_CHECKING:
    from pyclingo.types import (
        PREDICATE_CLASS_TYPE,
        PREDICATE_FIELD_TYPE,
        PREDICATE_RAW_INPUT_TYPE,
    )


@dataclass(frozen=True, eq=False)
class Predicate(BasicTerm):
    """
    This is a base class that represents a predicate in an ASP program.
    To define a predicate, subclass this class and add fields with names for each slot in the predicate,
    and give the attributes type PREDICATE_RAW_INPUT_TYPE.

    Predicates in ASP consist of a name and optional arguments.
    They can appear in rule heads and bodies, and can have Value
    or other Predicate objects as arguments.

    Note: == on a Value builds an ASP Comparison term (X == 5 renders as "X = 5"), but
    == on a predicate answers a question: two instances are equal iff they are the same
    predicate class with identically-rendered arguments, and they hash consistently, so
    instances can be used in sets and as dictionary keys. This asymmetry is deliberate —
    predicates round-trip through the solver as solution facts, i.e. data.
    """

    # Class-level attributes
    _namespace: ClassVar[str] = ""
    # Default visibility, fixed at define() time. Per-program overrides live in
    # ASPProgram (show/hide/show_when); nothing may mutate this after creation.
    _show: ClassVar[bool] = True

    def __init__(self, *args: PREDICATE_RAW_INPUT_TYPE, **kwargs: PREDICATE_RAW_INPUT_TYPE) -> None:
        # This empty init is just to satisfy the type checker for arbitrary arguments
        super().__init__(*args, **kwargs)

    @classmethod
    def define(cls, name: str, fields: list[str], namespace: str = "", show: bool = True) -> Type[Predicate]:
        """
        Dynamically create a new Predicate subclass.

        Args:
            name: The name of the predicate in ASP.
            fields: List of field names for the predicate's arguments.
            namespace: Optional namespace prefix for the predicate.
            show: Whether this predicate should be included in the show directive.

        Returns:
            A new Predicate subclass with the specified fields.

        Example:
            >>> Person = Predicate.define("person", ["name", "age"])
            >>> john = Person(name="john", age=30)
            >>> john.render()
            'person("john", 30)'

        Note that Python strings become quoted ASP string constants; for an unquoted
        symbolic constant argument like person(john), pass Symbol("john").
        """
        if not name or not name[0].islower():
            raise ValueError(f"Predicate name must start with a lowercase letter: {name}")

        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Predicate name can only contain letters, digits, and underscores: {name}")

        field_specs = [(field_name, "PREDICATE_RAW_INPUT_TYPE") for field_name in fields]

        # Create the new class with the provided name as the class name.
        # eq=False is essential: the generated __eq__ would compare field tuples, whose
        # elements have overloaded __eq__ returning always-truthy Comparisons — making
        # every same-class instance compare equal. We inherit Predicate's __eq__/__hash__.
        new_class = make_dataclass(  # type: ignore
            cls_name=name,
            fields=field_specs,
            bases=(cls,),
            frozen=True,
            eq=False,
        )

        assert issubclass(new_class, Predicate)

        new_class._namespace = namespace
        new_class._show = show

        return new_class  # type: ignore

    def __post_init__(self) -> None:
        """Validate all field values and convert literals to appropriate terms."""
        # Use object.__setattr__ since the dataclass is frozen
        for field_info in self.argument_fields():
            value = self[field_info.name]

            # Convert literals to appropriate Value objects
            if isinstance(value, int):
                object.__setattr__(self, field_info.name, Number(value))
            elif isinstance(value, str):
                object.__setattr__(self, field_info.name, String(value))
            elif not isinstance(value, (Value, Predicate, Expression, Pool)):
                raise TypeError(
                    f"Predicate argument {field_info.name} must be a Value, Predicate, Expression, Pool, int or str, "
                    f"got {type(value).__name__}"
                )

    @classmethod
    def argument_fields(cls) -> list[Field]:
        """Get fields that represent predicate arguments (not starting with _)."""
        return [f for f in fields(cls) if not f.name.startswith("_")]

    @classmethod
    def field_names(cls) -> list[str]:
        """Get field names that represent predicate arguments (not starting with _)."""
        return [f.name for f in fields(cls) if not f.name.startswith("_")]

    @property
    def arguments(self) -> list[PREDICATE_FIELD_TYPE]:
        """Get the values of all argument fields."""
        return [self[f.name] for f in self.argument_fields()]

    def __getitem__(self, key: str) -> Any:
        """Access field values by name; raises KeyError for unknown fields."""
        if key not in self.field_names():
            raise KeyError(f"Predicate has no field named '{key}'")
        return getattr(self, key)

    def items(self) -> list[tuple[str, PREDICATE_FIELD_TYPE]]:
        """Return (field_name, field_value) tuples for all argument fields."""
        return [(f.name, self[f.name]) for f in self.argument_fields()]

    @classmethod
    def get_name(cls) -> str:
        """Get the name of this predicate with namespace if any."""
        predicate_name = cls.__name__.lower()
        if cls._namespace:
            predicate_name = f"{cls._namespace}_{predicate_name}"
        return predicate_name

    @classmethod
    def get_arity(cls) -> int:
        """Returns the arity of the predicate."""
        return len([f for f in fields(cls) if not f.name.startswith("_")])

    @classmethod
    def shown_by_default(cls) -> bool:
        """Whether this predicate appears in output unless a program overrides it."""
        return cls._show

    @property
    def is_grounded(self) -> bool:
        """A predicate is grounded if all its arguments are grounded."""
        return all(arg.is_grounded for arg in self.arguments)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        if not self.argument_fields():
            return self.get_name()

        if len(self.arguments) == 1:
            args_str = self.arguments[0].render(context=RenderingContext.LONE_PREDICATE_ARGUMENT)
        else:
            args_str = ", ".join(arg.render() for arg in self.arguments)

        return f"{self.get_name()}({args_str})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Predicates are valid in both heads and bodies."""
        pass

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """Returns this predicate's class plus any predicate classes used as arguments."""
        predicates: set[PREDICATE_CLASS_TYPE] = {type(self)}

        for arg in self.arguments:
            predicates.update(arg.collect_predicates())

        return predicates

    def collect_defined_constants(self) -> set[str]:
        constants = set()

        for arg in self.arguments:
            constants.update(arg.collect_defined_constants())

        return constants

    def __eq__(self, other: object) -> bool:
        """
        Value equality: same predicate class and identically-rendered arguments.

        Rendered forms are compared because the arguments themselves overload __eq__
        to build Comparison terms rather than answer equality questions.

        Returns NotImplemented for non-Predicate operands so Python reflects the
        comparison to the other side (e.g. a Variable, whose __eq__ builds ASP terms).
        """
        if not isinstance(other, Predicate):
            return NotImplemented
        return type(self) is type(other) and self.render() == other.render()

    def __ne__(self, other: object) -> bool:
        if not isinstance(other, Predicate):
            return NotImplemented
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash((type(self), self.render()))

    def __neg__(self) -> "ClassicalNegation":
        """
        Support for using `-predicate` syntax to create classical negation.

        Returns:
            ClassicalNegation: A classical negation of this predicate.

        Example:
            >>> Person = Predicate.define("person", ["name"])
            >>> (-Person(name="john")).render()
            '-person("john")'
        """
        return ClassicalNegation(self)

    def __invert__(self) -> "DefaultNegation":
        """
        Support for using `~predicate` syntax to create default negation.

        Returns:
            DefaultNegation: A default negation of this predicate.

        Example:
            >>> Person = Predicate.define("person", ["name"])
            >>> (~Person(name="john")).render()
            'not person("john")'
        """
        return DefaultNegation(self)

    def collect_variables(self) -> set[str]:
        variables = set()

        for arg in self.arguments:
            variables.update(arg.collect_variables())

        return variables

    def canonical_str(self) -> str:
        """
        The canonical named-field form of this fact, e.g. number(loc=cell(row=1, col=1), value=6).

        This is the format recorded in expected-solutions files. Unlike the positional
        ASP text from str(), it names each field, so it reads without knowing field
        order and survives reordering. The three representations: str() is ASP,
        repr() is Python, canonical_str() is this explicit form.
        """
        if not self.argument_fields():
            return f"{self.get_name()}()"
        args = ", ".join(
            f"{f.name}={value.canonical_str() if isinstance(value, Predicate) else value.render()}"
            for f in self.argument_fields()
            for value in (self[f.name],)
        )
        return f"{self.get_name()}({args})"

    def __str__(self) -> str:
        """The predicate rendered as ASP text, e.g. name(value1, value2)."""
        return self.render()

    def __repr__(self) -> str:
        """A Python-syntax representation that could recreate this predicate."""
        if not self.argument_fields():
            return f"{self.__class__.__name__}()"

        kwargs = ", ".join(f"{f.name}={repr(self[f.name])}" for f in self.argument_fields())
        return f"{self.__class__.__name__}({kwargs})"


class NegatedLiteral(Term, ABC):
    """
    Abstract base class for negated literals in ASP programs.

    Negated literals are terms prefixed with negation operators:
    either default negation ('not') or classical negation ('-').
    """

    def __init__(self, term: Term):
        self._term = term

    @property
    def term(self) -> Term:
        """The term being negated."""
        return self._term

    @property
    def is_grounded(self) -> bool:
        """A negated literal is grounded if its term is grounded."""
        return self._term.is_grounded

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        return self._term.collect_predicates()

    def collect_defined_constants(self) -> set[str]:
        return self._term.collect_defined_constants()

    def collect_variables(self) -> set[str]:
        return self._term.collect_variables()


class DefaultNegation(NegatedLiteral):
    """
    Represents default negation ('not') in ASP programs.

    Default negation is used to express that a literal cannot be proven
    to be true (it may be either false or unknown).
    """

    def __init__(self, term: Union[Predicate, Comparison, NegatedLiteral]):
        """
        Initialize a default negation, simplifying nested negations:
        an odd number of negations is equivalent to 'not p', an even number to 'not not p'.
        """
        if not isinstance(term, (Predicate, Comparison, NegatedLiteral)):
            raise TypeError("Default negation can only be applied to predicates, comparisons, or already negated terms")

        if isinstance(term, DefaultNegation):
            inner_term = term.term
            if isinstance(inner_term, DefaultNegation):
                # not not not X -> simplify to not X
                # We're negating the inner term directly
                actual_term = inner_term.term
            else:
                # not not X -> just pass through the original term
                actual_term = term
        else:
            # Normal case: not X
            actual_term = term

        super().__init__(actual_term)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        term_str = self._term.render(context=RenderingContext.NEGATION)
        return f"not {term_str}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Default negation is body-only: raises in heads."""
        if is_in_head:
            raise ValueError("Default negation (not) cannot be used in rule heads")


class ClassicalNegation(NegatedLiteral):
    """
    Represents classical negation ('-') in ASP programs.

    Classical negation is used to express the explicit falsity of a predicate,
    rather than just the absence of proof.
    """

    def __init__(self, term: Union[Predicate, "ClassicalNegation"]):
        """Initialize a classical negation, simplifying double negation: -(-p) becomes p."""
        if not isinstance(term, (Predicate, ClassicalNegation)):
            raise TypeError("Classical negation can only be applied to predicates or classical negations")

        # Check if we're negating a negation: -(-p) -> simplify to p
        actual_term = term.term if isinstance(term, ClassicalNegation) else term

        super().__init__(actual_term)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        term_str = self._term.render()
        return f"-{term_str}"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Classical negation is valid in heads and bodies."""
        pass


def Not(term: Union[Predicate, Comparison, NegatedLiteral]) -> DefaultNegation:
    """
    Helper function to create default negation.

    This function applies default negation to the term, with automatic
    simplification of nested negations when appropriate.

    Args:
        term: The term to negate with default negation.

    Returns:
        Term: A default negation of the given term, simplified if needed.

    Example:
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
