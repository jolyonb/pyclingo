from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyclingo.types import PREDICATE_CLASS_TYPE


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

        Context is used to tell the term the context in which it is being rendered.
        Terms are responsible for wrapping themselves in parentheses as needed.

        Args:
            context: The context in which the Term is being rendered.

        Returns:
            str: The string representation of the term in Clingo syntax.
        """
        pass

    @property
    @abstractmethod
    def is_grounded(self) -> bool:
        """
        Determines if the term is fully grounded (contains no variables).

        Returns:
            bool: True if the term is grounded, False otherwise.
        """
        pass

    @abstractmethod
    def validate_in_context(self, is_in_head: bool) -> None:
        """
        Validates this term for use in a specific position (head or body).

        Args:
            is_in_head: True if validating for head position, False for body position.
        """
        pass

    @abstractmethod
    def collect_predicates(self) -> set[PREDICATE_CLASS_TYPE]:
        """
        Collects all predicate classes used in this term.

        Returns:
            set[type[predicate]]: A set of Predicate classes (not instances) used within this term.
        """
        pass

    @abstractmethod
    def collect_symbolic_constants(self) -> set[str]:
        """
        Collects all symbolic constant names used in this term.

        Returns:
            set[str]: A set of symbolic constant names used within this term.
        """
        pass

    @abstractmethod
    def collect_variables(self) -> set[str]:
        """
        Collects all variables used in this term.

        Returns:
            set[str]: A set of variables used within this term.
        """
        pass


class BasicTerm(Term, ABC):
    """
    Abstract base class for terms that can be direct predicate arguments.

    This includes values (variables, constants) and predicates themselves.
    BasicTerms are the fundamental building blocks for constructing ASP programs.
    """
