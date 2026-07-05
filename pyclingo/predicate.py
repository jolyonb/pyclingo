import keyword
import re
import types
from dataclasses import Field, dataclass, fields
from typing import Any, ClassVar, dataclass_transform

from pyclingo.core import (
    BasicTerm,
    Expression,
    Negatable,
    Number,
    Pool,
    RenderingContext,
    String,
    Value,
)

# Type aliases. PredicateField is any argument a predicate accepts, and doubles
# as the field annotation for class-syntax predicates
type PredicateField = int | str | Value | Predicate | Expression | Pool
type PREDICATE_FIELD_TYPE = Value | Predicate | Expression | Pool
type PREDICATE_CLASS_TYPE = type[Predicate]


def _validate_schema(name: str, namespace: str, field_names: list[str]) -> None:
    """Validate a predicate's ASP name, namespace, and field names, raising on any problem."""
    if not name or not name[0].islower():
        raise ValueError(f"Predicate name must start with a lowercase letter: {name}")

    if not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"Predicate name can only contain letters, digits, and underscores: {name}")

    if name == "not":
        raise ValueError("'not' is reserved in ASP and cannot be a predicate name")

    if namespace and (not namespace[0].islower() or not all(c.isalnum() or c == "_" for c in namespace)):
        raise ValueError(
            f"Namespace must start with a lowercase letter and contain only letters, "
            f"digits, and underscores: {namespace}"
        )

    if len(set(field_names)) != len(field_names):
        duplicates = sorted({f for f in field_names if field_names.count(f) > 1})
        raise ValueError(f"Duplicate field name(s): {', '.join(duplicates)}")

    reserved = _RESERVED_FIELD_NAMES
    for field_name in field_names:
        if not field_name.isidentifier() or field_name.startswith("_") or keyword.iskeyword(field_name):
            raise ValueError(
                f"Field name must be a valid non-keyword identifier not starting with an underscore: {field_name!r}"
            )
        if field_name in reserved:
            raise ValueError(f"Field name {field_name!r} would shadow a Predicate attribute")


# dataclass_transform tells type checkers that subclasses become dataclasses
# (with these frozen/eq settings), so they synthesize a typed __init__ from each
# subclass's annotated fields — typo'd or missing arguments are type errors.
# The runtime counterpart is __init_subclass__, which actually applies
# dataclass() to every subclass; the two must agree on the settings.
@dataclass_transform(frozen_default=True, eq_default=False, field_specifiers=())
@dataclass(frozen=True, eq=False)
class Predicate(BasicTerm, Negatable):
    """
    This is a base class that represents a predicate in an ASP program.

    Define a predicate either as a class, whose annotated fields are checked
    statically:

        class Person(Predicate):
            name: PredicateField
            age: PredicateField

    or dynamically via Predicate.define("person", ["name", "age"]) when the
    schema is only known at runtime. Class kwargs set the ASP name (defaults
    to the class name, snake-cased: HasSymbol -> has_symbol), namespace, and visibility:

        class Person(Predicate, name="person", show=False): ...

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
    _predicate_name: ClassVar[str]  # set for every subclass by __init_subclass__
    # Default visibility, fixed at class creation. Per-program overrides live in
    # ASPProgram (show/hide/show_when); nothing may mutate this after creation.
    _show: ClassVar[bool] = True

    def __init__(self, *args: PredicateField, **kwargs: PredicateField) -> None:
        # Satisfies the type checker for dynamically defined classes (type[Predicate]),
        # whose fields checkers cannot know. Never runs for concrete subclasses:
        # the dataclass transform generates their real __init__ (and dataclass()
        # does not clobber an explicitly defined one, so this survives on the base).
        super().__init__(*args, **kwargs)

    def __init_subclass__(cls, name: str | None = None, namespace: str = "", show: bool = True, **kwargs: Any) -> None:
        """
        Turn every subclass into a frozen predicate dataclass.

        This is the single creation path: class-syntax subclasses and define()
        both land here, so their instances behave identically. eq=False is
        essential — a generated __eq__ would compare field tuples, whose
        elements overload == to build always-truthy Comparisons; predicates
        inherit their own __eq__/__hash__ instead.
        """
        super().__init_subclass__(**kwargs)
        # The default ASP name snake-cases the class name: HasSymbol -> has_symbol
        cls._predicate_name = name if name is not None else re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
        cls._namespace = namespace
        cls._show = show
        _validate_schema(cls._predicate_name, namespace, list(cls.__annotations__ or {}))
        # dataclass() mutates cls in place (adding __init__ etc.) and returns it;
        # no reassignment is needed
        dataclass(frozen=True, eq=False)(cls)

    @classmethod
    def define(cls, name: str, field_names: list[str], namespace: str = "", show: bool = True) -> type[Predicate]:
        """
        Dynamically create a new Predicate subclass.

        Args:
            name: The name of the predicate in ASP.
            field_names: Names for the predicate's argument slots.
            namespace: Optional namespace prefix for the predicate.
            show: Whether this predicate should be included in the show directive.

        Returns:
            A new Predicate subclass with the specified fields.

        Example:
            >>> Person = Predicate.define("person", ["name", "age"])
            >>> john = Person(name="john", age=30)
            >>> john.render()
            'person("john", 30)'

        Note that Python strings become quoted ASP string constants. For an unquoted
        atom argument like person(john), define john as a nullary predicate:
        Predicate.define("john", [], show=False)().
        """

        # Validate the raw list here: the annotations dict would silently
        # collapse duplicates before __init_subclass__ could see them
        _validate_schema(name, namespace, field_names)

        def set_annotations(class_namespace: dict[str, Any]) -> None:
            class_namespace["__annotations__"] = dict.fromkeys(field_names, "PredicateField")

        new_class = types.new_class(
            name,
            bases=(cls,),
            kwds={"name": name, "namespace": namespace, "show": show},
            exec_body=set_annotations,
        )
        assert issubclass(new_class, Predicate)
        return new_class

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
        """Get the name of this predicate with namespace if any. Case is preserved."""
        predicate_name = cls._predicate_name
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

        kwargs = ", ".join(f"{f.name}={self[f.name]!r}" for f in self.argument_fields())
        return f"{self.__class__.__name__}({kwargs})"


# Field names that would shadow Predicate API; computed once Predicate exists
_RESERVED_FIELD_NAMES = frozenset(attr for attr in dir(Predicate) if not attr.startswith("__"))
