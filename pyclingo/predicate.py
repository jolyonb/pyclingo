from __future__ import annotations

from dataclasses import Field, dataclass, fields, make_dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Type

from pyclingo.term import BasicTerm
from pyclingo.value import Constant, StringConstant, Value

if TYPE_CHECKING:
    from pyclingo.conditional_literal import ConditionalLiteral
    from pyclingo.negation import ClassicalNegation
    from pyclingo.types import (
        PREDICATE_CLASS_TYPE,
        PREDICATE_FIELD_TYPE,
        PREDICATE_RAW_INPUT_TYPE,
        VARIABLE_TYPE,
    )


@dataclass(frozen=True)
class Predicate(BasicTerm):
    """
    This is a base class that represents a predicate in an ASP program.
    To define a predicate, subclass this class and add fields with names for each slot in the predicate,
    and give the attributes type PREDICATE_RAW_INPUT_TYPE.

    Predicates in ASP consist of a name and optional arguments.
    They can appear in rule heads and bodies, and can have Value
    or other Predicate objects as arguments.
    """

    # Class-level attributes
    _namespace: ClassVar[str] = ""
    _show: ClassVar[bool] = True
    _show_conditions: ClassVar[ConditionalLiteral | None] = None

    def __init__(self, *args: PREDICATE_RAW_INPUT_TYPE, **kwargs: PREDICATE_RAW_INPUT_TYPE) -> None:
        # This empty init is just to satisfy the type checker for arbitrary arguments
        super().__init__(*args, **kwargs)

    @classmethod
    def with_namespace(cls, namespace: str) -> PREDICATE_CLASS_TYPE:
        """
        Create a subclass of this predicate with the given namespace.

        Args:
            namespace: The namespace to add to the predicate

        Returns:
            A new predicate class with the same structure but a namespaced name
        """
        # Create a new class with the same structure but a different namespace
        return type(  # type: ignore
            f"{namespace}_{cls.__name__}",  # New class name for clarity
            (cls,),  # Inherit from the original class
            {"_namespace": namespace},  # Set the namespace
        )

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
            'person(john, 30)'
        """
        # Validate the predicate name
        if not name or not name[0].islower():
            raise ValueError(f"Predicate name must start with a lowercase letter: {name}")

        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Predicate name can only contain letters, digits, and underscores: {name}")

        # Create field specifications for make_dataclass
        field_specs = [(field_name, "pyclingo.types.PREDICATE_RAW_INPUT_TYPE") for field_name in fields]

        # Create the new class with the provided name as the class name
        new_class = make_dataclass(  # type: ignore
            cls_name=name,
            fields=field_specs,
            bases=(cls,),
            frozen=True,
        )

        assert issubclass(new_class, Predicate)

        # Set class-level attributes
        new_class._namespace = namespace
        new_class._show = show

        return new_class  # type: ignore

    def __post_init__(self) -> None:
        """Validate all field values and convert literals to appropriate terms."""
        from pyclingo.expression import Expression
        from pyclingo.pool import Pool

        # Use object.__setattr__ since the dataclass is frozen
        for field_info in self.argument_fields():
            value = self[field_info.name]

            # Convert literals to appropriate Value objects
            if isinstance(value, int):
                object.__setattr__(self, field_info.name, Constant(value))
            elif isinstance(value, str):
                object.__setattr__(self, field_info.name, StringConstant(value))
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
        """
        Access field values using dictionary-like syntax.

        Args:
            key: The name of the field to access

        Returns:
            The value of the field

        Raises:
            KeyError: If the field doesn't exist
        """
        if not hasattr(self, key):
            raise KeyError(f"Predicate has no field named '{key}'")
        return getattr(self, key)

    def items(self) -> list[tuple[str, PREDICATE_FIELD_TYPE]]:
        """
        Return a list of (field_name, field_value) tuples for all argument fields.

        Returns:
            List of (name, value) tuples
        """
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
    def get_show_directive(cls) -> str | None:
        """
        Constructs the show directive for this predicate, or returns None if it should remain hidden.

        Returns:
            str | None: Show directive for this predicate, or None
        """
        if not cls._show:
            return None
        if cls._show_conditions:
            signature = cls._show_conditions.render(as_argument=False)
        else:
            signature = f"{cls.get_name()}/{cls.get_arity()}"
        return f"#show {signature}."

    @classmethod
    def set_show_directive(cls, statement: ConditionalLiteral | None) -> None:
        """
        Sets the show directive for this predicate.
        """
        cls._show_conditions = statement

    @property
    def is_grounded(self) -> bool:
        """
        Determines if the predicate is fully grounded.

        A predicate is grounded if all its arguments are grounded.

        Returns:
            bool: True if the predicate is grounded, False otherwise.
        """
        return all(arg.is_grounded for arg in self.arguments)

    def render(self, as_argument: bool = False) -> str:
        """
        Renders the predicate as a string in Clingo syntax.

        Args:
            as_argument: Whether this term is being rendered as an argument
                        to another term (e.g., inside a predicate).

        Returns:
            str: The string representation of the predicate.
        """
        if not self.argument_fields():
            return self.get_name()

        args_str = ", ".join(arg.render(as_argument=True) for arg in self.arguments)
        return f"{self.get_name()}({args_str})"

    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this predicate for use in a specific position.

        Args:
            is_in_head: True if validating for head position, False for body position.
        """
        # Predicates can appear in both heads and bodies
        pass

    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this predicate.

        Returns the class of this predicate plus any predicates used as arguments.

        Returns:
            set[type[Predicate]]: A set of Predicate classes used in this predicate.
        """
        # Add this predicate's class to the set
        predicates: set[PREDICATE_CLASS_TYPE] = {type(self)}

        # Collect predicates from all arguments
        for arg in self.arguments:
            predicates.update(arg.collect_predicates())

        return predicates

    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this predicate.

        Returns:
            set[str]: A set of symbolic constant names used in this predicate.
        """
        constants = set()

        # Collect symbolic constants from all arguments
        for arg in self.arguments:
            constants.update(arg.collect_symbolic_constants())

        return constants

    def __neg__(self) -> "ClassicalNegation":
        """
        Support for using `-predicate` syntax to create classical negation.

        Returns:
            ClassicalNegation: A classical negation of this predicate.

        Example:
            >>> person = Person(name="john")
            >>> neg_person = -person  # Renders as: -person(john)
        """
        from pyclingo.negation import (
            ClassicalNegation,  # Import here to avoid circular imports
        )

        return ClassicalNegation(self)

    def collect_variables(self) -> set[VARIABLE_TYPE]:
        """
        Collects all variables used in this predicate's arguments.

        Returns:
            set[Variable]: A set of variables used in this predicate.
        """
        variables = set()

        # Collect variables from all arguments
        for arg in self.arguments:
            variables.update(arg.collect_variables())

        return variables

    def __str__(self) -> str:
        """
        Human-readable string representation of the predicate.

        Returns:
            A string in the format: name(arg1=value1, arg2=value2)
        """
        return self.render(as_argument=False)

    def __repr__(self) -> str:
        """
        Developer-friendly string representation of the predicate.

        Returns:
            A string that could be used to recreate this predicate
        """
        if not self.argument_fields():
            return f"{self.__class__.__name__}()"

        kwargs = ", ".join(f"{f.name}={repr(self[f.name])}" for f in self.argument_fields())
        return f"{self.__class__.__name__}({kwargs})"
