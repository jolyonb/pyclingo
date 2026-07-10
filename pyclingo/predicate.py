import keyword
import re
import threading
import types
from abc import ABCMeta
from dataclasses import Field as DataclassField
from dataclasses import dataclass, fields
from typing import Any, ClassVar, NoReturn, Self, cast, dataclass_transform, get_args, get_origin, overload

from pyclingo.core import (
    DefinedConstant,
    Expression,
    Negatable,
    Number,
    Pool,
    PredicateBase,
    PredicateOccurrence,
    RenderingContext,
    String,
    Value,
    Variable,
)
from pyclingo.source_location import SourceLocation, capture_location, capture_module

# Type aliases. PredicateField is any argument a predicate accepts, and doubles
# as the field annotation for class-syntax predicates
type PredicateField = int | str | Value | Predicate | Expression | Pool
# The Term view of a stored field: primitives are wrapped by read_as_term,
# so int/str never appear here (unlike PredicateField, the write union)
type FieldAsTermType = Value | Predicate | Expression | Pool
type PredicateClassType = type[Predicate]

# Serializes in_namespace()'s clone creation: racing callers must agree on
# one clone class per (base, namespace)
_clone_lock = threading.Lock()


class Field[T]:
    """
    A typed predicate field: annotate class-syntax fields as Field[int],
    Field[str], or Field[SomePredicate].

    A data descriptor with different read and write types. Writing accepts the
    ground type OR the rule-authoring terms (Variable, Expression, Pool,
    DefinedConstant), so Person(age=N) works in rules; reading is typed as the
    ground type, so model.atoms(Person)[0].age is an int to type checkers.
    Ground values are stored as plain Python values (a Number written here is
    unwrapped), and writes are validated against the ground type.

    Note the read-type contract: fields are typed by their ground schema. A
    rule atom like Person(age=N) transiently holds the Variable, which a type
    checker will still call int — reads of non-ground atoms are the one place
    the static types overpromise.

    Migration note: an UNTYPED field reads back as a wrapped term (atom.x is
    a Number), a typed one as the plain Python value (atom.x is an int) — so
    adding Field[...] to an existing schema changes every read site
    (atom.x.value breaks). Migrate the reads together with the annotation.
    """

    __slots__ = ("_ground_type", "_name")

    def __init__(self, name: str, ground_type: type) -> None:
        self._name = name
        self._ground_type = ground_type

    @overload
    def __get__(self, obj: None, owner: Any) -> Field[T]: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> T: ...

    def __get__(self, obj: object | None, owner: Any = None) -> Any:
        if obj is None:
            return self
        try:
            return obj.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None

    def __set__(self, obj: Any, value: T | Variable | Expression | Pool | DefinedConstant) -> None:
        # The frozen dataclass __init__ writes via object.__setattr__, which
        # routes through this data descriptor; storing in the instance dict
        # keeps the descriptor authoritative for reads
        obj.__dict__[self._name] = self._validated(value)

    def _validated(self, value: Any) -> Any:
        """Normalize a write to the ground type's plain value, or pass rule terms through."""
        if isinstance(value, (Variable, Expression, Pool, DefinedConstant)):
            return value
        ground = self._ground_type
        if ground is int:
            if isinstance(value, Number):
                return value.value
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Field '{self._name}' expects int, got {type(value).__name__}")
            return Number(value).value  # reuses Number's range validation
        if ground is str:
            if isinstance(value, String):
                return value.value
            if not isinstance(value, str):
                raise TypeError(f"Field '{self._name}' expects str, got {type(value).__name__}")
            return String(value).value  # reuses String's content validation
        # Ground type is a Predicate subclass
        if isinstance(value, ground):
            return value
        raise TypeError(f"Field '{self._name}' expects {ground.__name__}, got {type(value).__name__}")


def _field_ground_types(cls: type) -> dict[str, type]:
    """Map field names annotated as Field[...] to their ground types, raising on bad ones."""
    ground_types: dict[str, type] = {}
    for field_name, annotation in (cls.__annotations__ or {}).items():
        if isinstance(annotation, str) and annotation.replace(" ", "").startswith("Field["):
            # "from __future__ import annotations" stringifies annotations, which
            # would silently skip descriptor installation — no validation, no
            # plain-Python reads. Refuse loudly; the future import is unnecessary
            # on Python 3.14
            raise TypeError(
                f"Field[...] annotation on {cls.__name__}.{field_name} is a string — "
                f"remove 'from __future__ import annotations' from the defining module "
                f"(typed fields cannot be wired from stringified annotations)"
            )
        if get_origin(annotation) is Field:
            (ground,) = get_args(annotation)
            if (
                ground is not int
                and ground is not str
                and not (isinstance(ground, type) and issubclass(ground, Predicate))
            ):
                raise TypeError(f"Field[...] ground type must be int, str, or a Predicate subclass, got {ground!r}")
            ground_types[field_name] = ground
    return ground_types


def _validate_schema(name: str, namespace: str, field_names: list[str]) -> None:
    """Validate a predicate's ASP name, namespace, and field names, raising on any problem."""
    if not name.isascii():
        raise ValueError(f"Predicate name must be ASCII (gringo's lexer is ASCII-only): {name!r}")
    if not name or not name[0].islower():
        raise ValueError(f"Predicate name must start with a lowercase letter: {name}")

    if not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"Predicate name can only contain letters, digits, and underscores: {name}")

    if name == "not":
        raise ValueError("'not' is reserved in ASP and cannot be a predicate name")

    if not namespace.isascii():
        raise ValueError(f"Namespace must be ASCII (gringo's lexer is ASCII-only): {namespace!r}")
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
        if (
            not field_name.isascii()
            or not field_name.isidentifier()
            or field_name.startswith("_")
            or keyword.iskeyword(field_name)
        ):
            raise ValueError(
                f"Field name must be a valid ASCII non-keyword identifier not starting "
                f"with an underscore: {field_name!r}"
            )
        if field_name in reserved:
            raise ValueError(f"Field name {field_name!r} would shadow a Predicate attribute")


@dataclass(frozen=True)
class NegatedSignature:
    """
    The classically negated signature of a predicate class, written -P.

    Only meaningful in raw_asp(predicates=...): declaring -P tells pyclingo a
    raw block derives -p atoms, so their "#show -p/n." directive is emitted.
    (The positive class already round-trips and validates both signs — the
    sign lives on the atom — so this adds only the negated sign's visibility.)
    """

    predicate: type[Predicate]


class _PredicateMeta(ABCMeta):
    """
    Unary minus on a predicate CLASS: -P is NegatedSignature(P), for raw_asp
    declarations. (-p(1), minus on an instance, still negates the atom.)
    """

    def __neg__(cls) -> NegatedSignature:
        return NegatedSignature(cast("type[Predicate]", cls))


# dataclass_transform tells type checkers that subclasses become dataclasses
# (with these frozen/eq settings), so they synthesize a typed __init__ from each
# subclass's annotated fields — typo'd or missing arguments are type errors.
# The runtime counterpart is __init_subclass__, which actually applies
# dataclass() to every subclass; the two must agree on the settings.
@dataclass_transform(frozen_default=True, eq_default=False, field_specifiers=())
@dataclass(frozen=True, eq=False)
class Predicate(PredicateBase, Negatable, metaclass=_PredicateMeta):
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
    # Names of Field[...]-typed slots, whose descriptors validate and store
    # plain Python values; __post_init__ leaves them alone
    _descriptor_fields: ClassVar[frozenset[str]] = frozenset()
    # in_namespace() clones, cached so repeated calls return the same class —
    # two distinct classes sharing a (name, arity) would be a collision. The
    # dict lives in each base class's OWN __dict__ (created on first use,
    # never inherited), so dropping the base frees its clones: a define()
    # churn loop cannot pin classes forever through a process-global cache.
    _namespace_clones: ClassVar[dict[str, type[Predicate]]]
    # Where user code defined this class (its class statement, define() call,
    # or in_namespace() call); a name-collision error needs it — the colliding
    # classes' names match by definition, so names alone cannot disambiguate
    _defined_at: ClassVar[SourceLocation | None] = None
    # Nesting cap and per-instance depth (1 + deepest Predicate argument);
    # see __post_init__
    MAX_DEPTH: ClassVar[int] = 250
    _depth: ClassVar[int] = 0

    def __init__(self, *args: PredicateField, **kwargs: PredicateField) -> None:
        # Satisfies the type checker for dynamically defined classes (type[Predicate]),
        # whose fields checkers cannot know. Never runs for concrete subclasses:
        # the dataclass transform generates their real __init__ (and dataclass()
        # does not clobber an explicitly defined one, so this survives on the base) —
        # so anything that reaches it is a direct Predicate() instantiation, which
        # would construct a broken instance (no name, no fields)
        raise TypeError("Predicate cannot be instantiated directly; declare a subclass or use Predicate.define()")

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
        if not isinstance(show, bool):
            raise TypeError(f"show must be a bool, got {type(show).__name__}")
        # Right for class-syntax subclasses (the class statement's frame is
        # the first user frame); define() and in_namespace() go through
        # stdlib types.new_class, whose frame would be blamed instead, so
        # they re-stamp with their own caller after creation
        cls._defined_at = capture_location()
        # The default ASP name snake-cases the class name: HasSymbol -> has_symbol
        cls._predicate_name = name if name is not None else re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
        cls._namespace = namespace
        cls._show = show
        # ClassVar annotations are class-level helpers, not fields: dataclass
        # excludes them, and so does schema validation
        declared_fields = [
            field_name
            for field_name, annotation in (cls.__annotations__ or {}).items()
            if get_origin(annotation) is not ClassVar and annotation is not ClassVar
        ]
        _validate_schema(cls._predicate_name, namespace, declared_fields)
        ground_types = _field_ground_types(cls)
        # dataclass() mutates cls in place (adding __init__ etc.) and returns it;
        # no reassignment is needed. repr=False: the generated __repr__ would
        # shadow Predicate's sign-aware one on every subclass
        dataclass(frozen=True, eq=False, repr=False)(cls)
        # Install the Field descriptors only after dataclass() has run, so it
        # treats these as required fields rather than defaulted ones. Inherited
        # descriptor fields stay registered so __post_init__ keeps skipping them.
        for field_name, ground in ground_types.items():
            descriptor: Field[Any] = Field(field_name, ground)
            setattr(cls, field_name, descriptor)
        cls._descriptor_fields = cls._descriptor_fields | frozenset(ground_types)

    @classmethod
    def in_namespace(cls, namespace: str) -> type[Self]:
        """
        A copy of this predicate class under the given namespace.

        The copy is a cached subclass: its fields (including Field[...] typing)
        are inherited, repeated calls return the same class object, and
        instances of differently-namespaced copies are never equal — the
        namespace is part of a predicate's identity, fixed at creation.

        Example:
            >>> Clue = Predicate.define("clue", ["loc"])
            >>> GridClue = Clue.in_namespace("grid")
            >>> GridClue(loc=1).render()
            'grid_clue(1)'
            >>> Clue.in_namespace("grid") is GridClue
            True
        """
        if namespace == cls._namespace:
            return cls  # already in this namespace
        # Locked: racing callers must agree on ONE clone class — two distinct
        # classes sharing (name, arity) would trip the collision check later
        with _clone_lock:
            clones = cls.__dict__.get("_namespace_clones")
            if clones is None:
                clones = {}
                cls._namespace_clones = clones
            clone = clones.get(namespace)
            if clone is None:
                clone = types.new_class(
                    cls.__name__,
                    bases=(cls,),
                    kwds={"name": cls._predicate_name, "namespace": namespace, "show": cls._show},
                )
                assert issubclass(clone, Predicate)
                # Attribute to the caller, not types.new_class's frame: the
                # location AND the module (unfixed, __module__ blames the
                # class-creation machinery in every repr and pickle error)
                clone._defined_at = capture_location()
                if (module := capture_module()) is not None:
                    clone.__module__ = module
                clones[namespace] = clone
        return cast(type[Self], clone)

    @classmethod
    def define(
        cls,
        name: str,
        field_names: list[str] | dict[str, type | None],
        namespace: str = "",
        show: bool = True,
    ) -> type[Self]:
        """
        Dynamically create a new Predicate subclass (of the class it is called
        on, so GridCell.define(...) returns a GridCell subclass).

        Args:
            name: The name of the predicate in ASP.
            field_names: Names for the predicate's argument slots. Pass a dict
                mapping names to int, str, or a Predicate subclass to get
                runtime-typed slots: writes are validated per field (a solution
                atom carrying the wrong type fails loudly at load) and
                attribute reads return plain Python values. A None value leaves
                that slot untyped, for mixed schemas.
            namespace: Optional namespace prefix for the predicate.
            show: Whether this predicate should be included in the show directive.

        Returns:
            A new Predicate subclass with the specified fields.

        Example:
            >>> Person = Predicate.define("person", ["name", "age"])
            >>> john = Person(name="john", age=30)
            >>> john.render()
            'person("john", 30)'
            >>> Clue = Predicate.define("clue", {"loc": str, "value": int})
            >>> Clue(loc="a1", value="7")
            Traceback (most recent call last):
                ...
            TypeError: Field 'value' expects int, got str

        Note that Python strings become quoted ASP string constants. For an unquoted
        atom argument like person(john), define john as a nullary predicate:
        Predicate.define("john", [], show=False)().
        """

        if isinstance(field_names, str):
            raise TypeError(
                f"field_names takes a list or dict, not a bare string: "
                f"list({field_names!r}) would make one field per character "
                f"({list(field_names)!r}). Wrap it: [{field_names!r}]."
            )
        # Validate the raw list here: the annotations dict would silently
        # collapse duplicates before __init_subclass__ could see them
        _validate_schema(name, namespace, list(field_names))

        # Typed slots become Field[...] annotations, riding the same wiring as
        # class-syntax predicates; a plain list means every slot accepts anything
        annotations: dict[str, Any]
        if isinstance(field_names, dict):
            annotations = {
                # Subscripting with a runtime value is meaningless to mypy but is
                # exactly what __class_getitem__ does at runtime; None means untyped
                field_name: Field[ground] if ground is not None else "PredicateField"  # type: ignore[valid-type]
                for field_name, ground in field_names.items()
            }
        else:
            annotations = dict.fromkeys(field_names, "PredicateField")

        def set_annotations(class_namespace: dict[str, Any]) -> None:
            class_namespace["__annotations__"] = annotations

        new_class = types.new_class(
            name,
            bases=(cls,),
            kwds={"name": name, "namespace": namespace, "show": show},
            exec_body=set_annotations,
        )
        assert issubclass(new_class, cls)
        # Attribute to the caller, not types.new_class's frame: the location
        # AND the module (unfixed, __module__ blames the class-creation
        # machinery in every repr and pickle error)
        new_class._defined_at = capture_location()
        if (module := capture_module()) is not None:
            new_class.__module__ = module
        return cast(type[Self], new_class)

    def __post_init__(self) -> None:
        """Validate all field values and convert literals to appropriate terms."""
        # Use object.__setattr__ since the dataclass is frozen. Atoms are born
        # positive; __neg__ produces the classically negated copy
        object.__setattr__(self, "_negated", False)
        for field_info in self.argument_fields():
            if field_info.name in type(self)._descriptor_fields:
                continue  # the Field descriptor already validated and stored this one
            value = getattr(self, field_info.name)

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

        # Nesting cap, mirroring Expression.MAX_DEPTH: the tree walkers
        # recurse per level, and a linked-list encoding accumulated in a loop
        # (chain = wrap(chain)) would die mid-walk with a raw RecursionError
        depth = 1 + max(
            (
                argument._depth
                for field_info in self.argument_fields()
                if isinstance(argument := getattr(self, field_info.name), Predicate)
            ),
            default=0,
        )
        if depth > self.MAX_DEPTH:
            raise ValueError(
                f"This predicate nests more than {self.MAX_DEPTH} levels deep — almost "
                f"certainly accumulated in a loop (chain = wrap(chain)). Deeper nesting "
                f"overflows Python's recursion inside the tree walkers; encode the chain "
                f"as indexed facts instead (e.g. link(I, I + 1))."
            )
        object.__setattr__(self, "_depth", depth)

    @classmethod
    def argument_fields(cls) -> list[DataclassField]:
        """Get fields that represent predicate arguments (not starting with _)."""
        return [f for f in fields(cls) if not f.name.startswith("_")]

    @classmethod
    def field_names(cls) -> list[str]:
        """Get field names that represent predicate arguments (not starting with _)."""
        return [f.name for f in cls.argument_fields()]

    def read_as_term(self, field_name: str) -> FieldAsTermType:
        """
        Read a field as a Term: the plain int/str values that Field[...]-typed
        slots store are wrapped back into Number/String (cached, so this is
        cheap). All internal machinery and square-bracket access (pred["x"])
        read through here, keeping everything downstream polymorphic over
        Term; attribute access (pred.x) on Field-typed slots is the
        plain-Python view.
        """
        value = getattr(self, field_name)
        if isinstance(value, int):
            return Number(value)
        if isinstance(value, str):
            return String(value)
        return cast(FieldAsTermType, value)

    @property
    def arguments(self) -> list[FieldAsTermType]:
        """Get the values of all argument fields, as Terms."""
        return [self.read_as_term(f.name) for f in self.argument_fields()]

    def __getitem__(self, key: str) -> Any:
        """Access field values by name, as Terms; raises KeyError for unknown fields."""
        if key not in self.field_names():
            raise KeyError(f"Predicate has no field named '{key}'")
        return self.read_as_term(key)

    def items(self) -> list[tuple[str, FieldAsTermType]]:
        """Return (field_name, field_value) tuples for all argument fields, values as Terms."""
        return [(f.name, self.read_as_term(f.name)) for f in self.argument_fields()]

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
        return len(cls.argument_fields())

    @classmethod
    def shown_by_default(cls) -> bool:
        """Whether this predicate appears in output unless a program overrides it."""
        return cls._show

    @property
    def is_grounded(self) -> bool:
        """A predicate is grounded if all its arguments are grounded."""
        return all(arg.is_grounded for arg in self.arguments)

    def render(self, context: RenderingContext = RenderingContext.DEFAULT) -> str:
        sign = "-" if self.negated else ""
        if not self.argument_fields():
            return f"{sign}{self.get_name()}"

        if len(self.arguments) == 1:
            args_str = self.arguments[0].render(context=RenderingContext.LONE_PREDICATE_ARGUMENT)
        else:
            args_str = ", ".join(arg.render() for arg in self.arguments)

        return f"{sign}{self.get_name()}({args_str})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """Predicates are valid in both heads and bodies."""
        pass

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

    def __hash__(self) -> int:
        return hash((type(self), self.render()))

    def collect_variables(self) -> set[str]:
        variables = set()

        for arg in self.arguments:
            variables.update(arg.collect_variables())

        return variables

    @property
    def negated(self) -> bool:
        """Whether this atom is classically negated (-p(...))."""
        return self._negated  # type: ignore[attr-defined, no-any-return]

    def __neg__(self) -> Self:
        """
        The classically negated copy of this atom: -p(1) asserts that p(1)
        is false — a distinct atom, and deriving both makes the program
        UNSAT. The sign is part of the atom, exactly as in clingo's own
        symbol model; negating a negated atom gives back the positive one.
        """
        # A field-sharing duplicate, built directly: __copy__ returns self
        # (predicates are immutable data), so it cannot make the distinct
        # object the sign flip needs
        negation = object.__new__(type(self))
        for key, value in self.__dict__.items():
            object.__setattr__(negation, key, value)
        object.__setattr__(negation, "_negated", not self.negated)
        return negation

    def __copy__(self) -> Self:
        """Predicates are immutable data: the copy IS the original (as for Values)."""
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """
        Immutable, holding interned Values: the deep copy IS the original.
        A distinct copy would carry equal-but-not-identical Values past
        their cache, breaking the same-object guarantee identity hashing
        rests on.
        """
        return self

    def __reduce__(self) -> NoReturn:
        """Copy goes through the hooks above; this one is pickle's, and it refuses loudly."""
        raise TypeError(
            f"{type(self).__name__} atoms do not pickle: a runtime-built class "
            f"(Predicate.define()) cannot be found by name on import, and the interned "
            f"Values inside would come back un-interned, silently losing their identity "
            f"guarantees. Transport atoms as text instead: render() them out and rebuild "
            f"with {type(self).__name__}(...) on the other side."
        )

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        # The one node that reads as_argument: this occurrence is an atom
        # unless it was placed as an argument (is_atom = not as_argument). A
        # predicate's own arguments are always arguments, so they recurse with
        # as_argument True — still collected, since the converter needs nested
        # classes registered. See Term.collect_predicate_occurrences.
        occurrences: set[PredicateOccurrence] = {(type(self), self.negated, not as_argument)}
        for arg in self.arguments:
            occurrences.update(arg.collect_predicate_occurrences(as_argument=True))
        return occurrences

    def canonical_str(self) -> str:
        """
        The canonical named-field form of this fact, e.g. number(loc=cell(row=1, col=1), value=6).

        This is the format recorded in expected-solutions files. Unlike the positional
        ASP text from str(), it names each field, so it reads without knowing field
        order and survives reordering. The three representations: str() is ASP,
        repr() is Python, canonical_str() is this explicit form.
        """
        sign = "-" if self.negated else ""
        if not self.argument_fields():
            return f"{sign}{self.get_name()}()"
        args = ", ".join(
            f"{f.name}={value.canonical_str() if isinstance(value, Predicate) else value.render()}"
            for f in self.argument_fields()
            for value in (self[f.name],)
        )
        return f"{sign}{self.get_name()}({args})"

    def __str__(self) -> str:
        """The predicate rendered as ASP text, e.g. name(value1, value2)."""
        return self.render()

    def __repr__(self) -> str:
        """A Python-syntax representation that could recreate this predicate."""
        sign = "-" if self.negated else ""
        if not self.argument_fields():
            return f"{sign}{self.__class__.__name__}()"

        kwargs = ", ".join(f"{f.name}={self[f.name]!r}" for f in self.argument_fields())
        return f"{sign}{self.__class__.__name__}({kwargs})"


# Field names that would shadow Predicate API; computed once Predicate exists
_RESERVED_FIELD_NAMES = frozenset(attr for attr in dir(Predicate) if not attr.startswith("__"))
