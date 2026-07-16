import keyword
import re
import sys
import threading
import types
from abc import ABCMeta
from dataclasses import Field as DataclassField
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Never, Self, SupportsIndex, cast, dataclass_transform, get_args, get_origin, overload

from aspalchemy.core import (
    DefaultNegation,
    DefinedConstant,
    ExplicitPool,
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
from aspalchemy.source_location import SourceLocation, capture_location, capture_origin

# Type aliases.
# PredicateArg — every value a predicate argument can hold. The polymorphic
# field slot is spelled Field[PredicateArg], so EVERY field is a Field[...];
# _field_ground_types recognizes this exact alias as the polymorphic marker.
type PredicateArg = int | str | Value | Predicate | Expression | Pool
# The Term view of a stored field: primitives are wrapped by read_as_term,
# so int/str never appear here (unlike the PredicateArg write union)
type FieldAsTermType = Value | Predicate | Expression | Pool
# The tuple-term universe shared by aggregates, #minimize/#maximize, and weak
# constraints — exactly coerce_tuple_term's domain
type TupleTermType = int | str | Value | Expression | Predicate

# Serializes in_namespace()'s clone creation: racing callers must agree on
# one clone class per (base, namespace)
_clone_lock = threading.Lock()


def coerce_tuple_term(term: object, noun: str) -> Value | Expression | Predicate:
    """
    Convert one entry of an element tuple (aggregate, #minimize/#maximize,
    or weak constraint) into a Term: a plain int becomes a Number, a plain
    str becomes a String — the same coercion predicate arguments perform —
    and Terms pass through unchanged. bool and anything else are rejected;
    noun labels the error with the construct doing the rejecting (e.g.
    "Aggregate").
    """
    if isinstance(term, bool):
        raise TypeError(f"{noun} tuple terms must be Values, Expressions, or Predicates, got bool")
    if isinstance(term, int):
        return Number(term)
    if isinstance(term, str):
        return String(term)
    if not isinstance(term, (Value, Expression, Predicate)):
        raise TypeError(f"{noun} tuple terms must be Values, Expressions, or Predicates, got {type(term).__name__}")
    return term


class Field[T]:
    """
    A typed predicate field: annotate class-syntax fields as Field[int],
    Field[str], or Field[SomePredicate]; use Field[PredicateArg] for a slot that
    must hold anything.

    A data descriptor with different read and write types. Writing accepts the
    ground type OR the rule-authoring terms (Variable, Expression, Pool,
    DefinedConstant), so Person(age=N) works in rules; ground writes are
    validated and normalized to plain Python (a Number written to an int field
    is unwrapped and stored as an int). Reading returns the stored plain value,
    so model.atoms(Person)[0].age is a real int — for EVERY field, typed or
    polymorphic. The Term view (Number/String wrapping) is reached through
    square-bracket access (atom["x"]) and read_as_term(); attribute access is
    always the plain-Python view.

    Note the read-type contract: fields are typed by their ground schema. A
    rule atom like Person(age=N) transiently holds the Variable, which a type
    checker will still call int — reads of non-ground atoms are the one place
    the static types overpromise.
    """

    __slots__ = ("_ground_type", "_name")

    def __init__(self, name: str, ground_type: type | None) -> None:
        # ground_type is None for a polymorphic (Field[PredicateArg]) slot
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
        if ground is None:
            return self._validated_polymorphic(value)
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

    def _validated_polymorphic(self, value: Any) -> Any:
        """
        A polymorphic (Field[PredicateArg]) slot: accept any predicate argument, unwrapping the
        primitive wrappers so the read side is plain Python (Number(5) and 5
        both store as the int 5), exactly as a typed field would.
        """
        if isinstance(value, Number):
            return value.value
        if isinstance(value, String):
            return value.value
        if isinstance(value, int):
            return Number(value).value  # rejects bool, validates int32 range
        if isinstance(value, str):
            return String(value).value  # validates content
        if isinstance(value, tuple):
            # The read side teaches the same idiom for clingo tuples
            raise TypeError(
                f"Predicate argument {self._name} is the tuple {value!r}, which aspalchemy "
                f"does not model — wrap it in a named predicate (pair(1, 2) instead of (1, 2))."
            )
        if isinstance(value, (Value, Predicate)):
            return value
        # The message names Expression and Pool as acceptable because they ARE
        # valid on the field — but as rule terms they were returned by the guard
        # at the top of _validated and never reach here, so this branch does not
        # handle them. Only ground values (and stray types) land on this raise.
        raise TypeError(
            f"Predicate argument {self._name} must be a Value, Predicate, Expression, Pool, "
            f"int or str, got {type(value).__name__}"
        )


# The ready-made Field[PredicateArg] object define() drops into annotations for a
# polymorphic slot (a plain list, or a None-valued dict entry).
_POLYMORPHIC_FIELD = Field[PredicateArg]


def _field_ground_types(cls: type) -> dict[str, type | None]:
    """
    Map the Field[...]-annotated slots to their ground types (None = polymorphic,
    i.e. Field[PredicateArg]), in declaration order, raising on bad ones. Only OWN
    annotations are read — inherited fields keep the base's descriptors.
    """
    ground_types: dict[str, type | None] = {}
    for field_name, annotation in (cls.__annotations__ or {}).items():
        if isinstance(annotation, str):
            # "from __future__ import annotations" stringifies every annotation,
            # leaving field descriptors unwired and ClassVars unrecognized —
            # Predicate needs real annotation objects. Refuse loudly; the future
            # import is unnecessary on Python 3.14.
            raise TypeError(
                f"Annotation on {cls.__name__}.{field_name} is the string {annotation!r} — "
                f"remove 'from __future__ import annotations' from the defining module "
                f"(predicate fields cannot be wired from stringified annotations)"
            )
        if annotation is Field:
            # A bare, unsubscripted Field is always a mistake — it carries no
            # ground type, so refuse it the way Field[Any] is refused.
            raise TypeError(
                f"{cls.__name__}.{field_name} is annotated with a bare Field — it needs a type "
                f"argument: Field[int], Field[str], Field[SomePredicate], or Field[PredicateArg] "
                f"for a polymorphic slot."
            )
        if get_origin(annotation) is Field:
            (ground,) = get_args(annotation)
            if ground is int or ground is str or (isinstance(ground, type) and issubclass(ground, Predicate)):
                ground_types[field_name] = ground
            elif ground is PredicateArg:
                ground_types[field_name] = None  # Field[PredicateArg]: a polymorphic slot
            else:
                raise TypeError(
                    f"Field[...] ground type must be int, str, a Predicate subclass, or "
                    f"PredicateArg (for a polymorphic slot): got {ground!r}. For a slot that "
                    f"holds anything write Field[PredicateArg] — Field[Any] and hand-written "
                    f"unions are not accepted."
                )
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

    Only meaningful in raw_asp(predicates=...): declaring -P tells aspalchemy a
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
            name: Field[str]
            age: Field[int]

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
    # The argument names in declaration order (inherited + own), cached once at
    # class creation so rendering/eq/repr never call dataclasses.fields() at
    # runtime. Every argument is a Field[...] descriptor slot.
    _field_names: ClassVar[tuple[str, ...]] = ()
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

    def __init__(self, *args: PredicateArg, **kwargs: PredicateArg) -> None:
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
        # A predicate's arguments are EXACTLY its Field[...] slots (Field[PredicateArg]
        # included). ClassVars are class-level helpers, and must not shadow a
        # Predicate member. ANY OTHER annotation is refused, naming the fix: an
        # ambiguous `note: str = ...` attribute is a ClassVar or a bare
        # (unannotated) assignment, never an argument — so nothing is ever
        # silently dropped from the signature. Everything surviving here is a
        # Field slot or a ClassVar, both of which dataclass() handles.
        ground_types = _field_ground_types(cls)
        # A subclass may only ADD fields. Re-declaring an inherited field would
        # make dataclass() read the base's descriptor (a class attribute) as a
        # DEFAULT — yielding a leaky "non-default follows default" error, or a
        # silently-optional field — so refuse it with a teaching message.
        inherited_fields = {name for base in cls.__mro__[1:] for name in getattr(base, "_field_names", ())}
        for field_name in ground_types:
            if field_name in inherited_fields:
                raise TypeError(
                    f"{cls.__name__}.{field_name} re-declares the inherited field {field_name!r}; "
                    f"a predicate subclass may only add fields, not re-type inherited ones."
                )
            # The mirror collision: a NEW field whose name is INHERITED class
            # data (a base ClassVar or attribute). dataclass() would read that
            # value as the field's DEFAULT — a silently-optional field whose
            # default nobody wrote. A value assigned in THIS class body is the
            # documented spelling of a deliberate default and stays legal;
            # reserved names fall through to _validate_schema's refusal below.
            if field_name not in _RESERVED_FIELD_NAMES and field_name not in vars(cls) and hasattr(cls, field_name):
                raise TypeError(
                    f"{cls.__name__}.{field_name} is declared Field[...], but {field_name!r} is inherited "
                    f"class data (a base-class ClassVar or attribute), which dataclass() would read as a "
                    f"silent default. Rename the field, or assign a default explicitly if one is intended."
                )
        # The same re-declaration refusal, for the other spellings: a ClassVar,
        # a bare (unannotated) assignment, or a def reusing an inherited field's
        # name would corrupt the schema silently — dataclass() DELETES a field
        # re-annotated as ClassVar, and any plain class attribute shadows the
        # base's Field descriptor in the MRO, so writes skip all validation.
        for member_name in sorted(inherited_fields & (set(cls.__annotations__ or ()) | set(vars(cls)))):
            raise TypeError(
                f"{cls.__name__}.{member_name} shadows the inherited field {member_name!r}; "
                f"class data may not reuse an inherited field's name. Rename one of them."
            )
        # Validate all the dataclass fields
        for field_name, annotation in (cls.__annotations__ or {}).items():
            if field_name in ground_types:
                continue
            if annotation is ClassVar or get_origin(annotation) is ClassVar:
                if field_name in _RESERVED_FIELD_NAMES:
                    raise ValueError(f"ClassVar {field_name!r} would shadow a Predicate attribute")
                continue
            if annotation is PredicateArg:
                raise TypeError(
                    f"{cls.__name__}.{field_name}: a polymorphic slot is spelled Field[PredicateArg], "
                    f"not a bare PredicateArg (every field is a Field[...])."
                )
            raise TypeError(
                f"{cls.__name__}.{field_name} is annotated {annotation!r}, which is not a predicate "
                f"field. Arguments must be Field[int], Field[str], Field[SomePredicate], or "
                f"Field[PredicateArg]; other class data must be a ClassVar or an unannotated attribute."
            )
        _validate_schema(cls._predicate_name, namespace, list(ground_types))
        # dataclass() mutates cls in place (adding __init__ etc.) and returns it;
        # no reassignment is needed. repr=False: the generated __repr__ would
        # shadow Predicate's sign-aware one on every subclass
        dataclass(frozen=True, eq=False, repr=False)(cls)
        # dataclass() generates a fields-based __replace__ on every subclass,
        # which would shadow the sign-preserving hook below: restore ours
        cls.__replace__ = Predicate.__replace__  # type: ignore[method-assign]
        # Install the Field descriptors only after dataclass() has run, so it
        # treats these as required fields rather than defaulted ones. Inherited
        # fields keep the base class's descriptors (resolved via the MRO).
        for field_name, ground in ground_types.items():
            descriptor: Field[Any] = Field(field_name, ground)
            setattr(cls, field_name, descriptor)
        # Cache the full ordered argument-name list (inherited + own) once, so no
        # runtime path pays for dataclasses.fields() again.
        cls._field_names = tuple(f.name for f in fields(cls))

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
                clone._defined_at, module = capture_origin()
                if module is not None:
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
            field_names: Names for the predicate's argument slots. A plain list
                makes every slot polymorphic (Field[PredicateArg]). Pass a dict
                mapping names to int, str, or a Predicate subclass to get
                runtime-typed slots: writes are then validated against the
                ground type (a solution atom carrying the wrong type fails
                loudly at load). A None value leaves that slot polymorphic, for
                mixed schemas. Reads are plain Python either way.
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
                # exactly what __class_getitem__ does at runtime; None means the
                # polymorphic Field[PredicateArg] slot
                field_name: Field[ground] if ground is not None else _POLYMORPHIC_FIELD  # type: ignore[valid-type]
                for field_name, ground in field_names.items()
            }
        else:
            annotations = dict.fromkeys(field_names, _POLYMORPHIC_FIELD)

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
        new_class._defined_at, module = capture_origin()
        if module is not None:
            new_class.__module__ = module
        return cast(type[Self], new_class)

    def __post_init__(self) -> None:
        """Fix the sign and enforce the nesting cap; the Field descriptors already validated writes."""
        # Use object.__setattr__ since the dataclass is frozen. Atoms are born
        # positive; __neg__ produces the classically negated copy. Every argument
        # was validated and normalized to plain Python by its Field descriptor on
        # write, so there is nothing to convert here.
        object.__setattr__(self, "_negated", False)

        # Nesting cap, mirroring Expression.MAX_DEPTH: the tree walkers
        # recurse per level, and a linked-list encoding accumulated in a loop
        # (chain = wrap(chain)) would die mid-walk with a raw RecursionError
        depth = 1 + max(
            (
                argument._depth
                for field_name in type(self)._field_names
                if isinstance(argument := getattr(self, field_name), (Predicate, ExplicitPool))
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
        """
        The dataclass Field objects for this predicate's arguments. Kept for
        callers wanting the field metadata; the hot paths use the cached
        _field_names tuple instead.
        """
        return list(fields(cls))

    @classmethod
    def field_names(cls) -> list[str]:
        """The predicate's argument names, in declaration order."""
        return list(cls._field_names)

    def read_as_term(self, field_name: str) -> FieldAsTermType:
        """
        Read a field as a Term: the plain int/str values that fields store are
        wrapped back into Number/String (cached, so this is cheap). All internal
        machinery and square-bracket access (pred["x"]) read through here,
        keeping everything downstream polymorphic over Term; attribute access
        (pred.x) is the plain-Python view.
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
        return [self.read_as_term(name) for name in type(self)._field_names]

    def __getitem__(self, key: str) -> Any:
        """Access field values by name, as Terms; raises KeyError for unknown fields."""
        if key not in type(self)._field_names:
            raise KeyError(f"Predicate has no field named '{key}'")
        return self.read_as_term(key)

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
        return len(cls._field_names)

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
        arguments = self.arguments
        if not arguments:
            return f"{sign}{self.get_name()}"

        if len(arguments) == 1:
            args_str = arguments[0].render(context=RenderingContext.LONE_PREDICATE_ARGUMENT)
        else:
            args_str = ", ".join(arg.render() for arg in arguments)

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

    def __replace__(self, /, **changes: Any) -> Self:
        """
        copy.replace(atom, field=...): field changes with the SIGN
        preserved — the sign is not a dataclass field, so the default
        reconstruction would silently return the positive atom. NOTE:
        dataclasses.replace() bypasses this hook entirely (its
        reconstruction is fields-based, no stdlib hook exists) and DOES
        drop the sign — use copy.replace. Both behaviors are pinned.
        """
        merged = {name: getattr(self, name) for name in type(self)._field_names} | changes
        replaced = type(self)(**merged)
        return -replaced if self.negated else replaced

    def __or__(self, other: object) -> Never:
        """p | q is a disjunction attempt: always raises, teaching the modeled spellings."""
        raise TypeError(
            "aspalchemy does not model disjunctive heads (p | q): "
            "A Choice with at_least(1) covers most uses, raw_asp() the rest"
        )

    def __invert__(self) -> DefaultNegation:
        """~atom builds "not atom". (On a plain comparison, ~ builds the complement instead — see Not.)"""
        # Overridden for the precise return type: an assumptions list wants
        # Predicate | DefaultNegation, and ~atom is always the latter
        return DefaultNegation(self)

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

    def __reduce_ex__(self, protocol: SupportsIndex) -> Any:
        """
        Copy goes through the hooks above and never reaches this one —
        this is pickle's alone. An atom pickles by the default machinery
        when its class can be found by name on import (class-syntax
        predicates at module level): the instance dict carries the sign
        and the field values, and any Values inside re-intern through
        their own __reduce__, so identity guarantees survive the round
        trip. A runtime-built class (define()/in_namespace()) cannot be
        found — its __module__ names the caller, but no module attribute
        holds it — so its atoms refuse loudly; the gate applies to nested
        atoms too, when pickle reaches them. The whole story: "Copying,
        Pickling, and Identity" in src/aspalchemy/CLAUDE.md.
        """
        cls = type(self)
        resolved: object = sys.modules.get(cls.__module__)
        for part in cls.__qualname__.split("."):
            resolved = getattr(resolved, part, None)
        if resolved is not cls:
            raise TypeError(
                f"{cls.__name__} atoms do not pickle: the class was built at runtime "
                f"(Predicate.define()/in_namespace()) and cannot be found by name on "
                f"import. Class-syntax predicates at module level pickle fine; "
                f"otherwise transport atoms as text — render() them out and rebuild "
                f"with {cls.__name__}(...) on the other side."
            )
        return super().__reduce_ex__(protocol)

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
        field_names = type(self)._field_names
        if not field_names:
            return f"{sign}{self.get_name()}()"
        args = ", ".join(
            f"{name}={value.canonical_str() if isinstance(value, Predicate) else value.render()}"
            for name in field_names
            for value in (self[name],)
        )
        return f"{sign}{self.get_name()}({args})"

    def __str__(self) -> str:
        """The predicate rendered as ASP text, e.g. name(value1, value2)."""
        return self.render()

    def __repr__(self) -> str:
        """A Python-syntax representation that could recreate this predicate."""
        sign = "-" if self.negated else ""
        field_names = type(self)._field_names
        if not field_names:
            return f"{sign}{self.__class__.__name__}()"

        kwargs = ", ".join(f"{name}={getattr(self, name)!r}" for name in field_names)
        return f"{sign}{self.__class__.__name__}({kwargs})"


# Field names that would shadow Predicate API; computed once Predicate exists
_RESERVED_FIELD_NAMES = frozenset(attr for attr in dir(Predicate) if not attr.startswith("__"))
