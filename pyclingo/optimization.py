"""
Optimization directives: #minimize and #maximize statements.

Aggregate-SHAPED but not aggregate-NATURED: an optimization element shares
the "targets : conditions" grammar (ConditionedElement) and the weighted
tuple form of #sum, but the directive is a program statement, not a term —
it compares with nothing and appears in no rule. The weight carries an
optional priority (rendered W@P): clasp optimizes lexicographically by
priority, highest first, and priorities are ordinal keys — gaps are free
(@10 and @0 behave exactly like @1 and @0).

Each minimize()/maximize() call renders as its own statement. All
optimization statements at a priority level contribute tuples to ONE
set — duplicate tuples count once, whichever statement (or weak
constraint) produced them — and the weight sums over the distinct set,
so accumulating elements into one statement would be cosmetic only.
"""

import re
from enum import StrEnum

from pyclingo.conditioned_element import CONDITION_TYPE, ConditionedElement
from pyclingo.core import AtomSign, Expression, Number, String, Term, Value, Variable
from pyclingo.predicate import Predicate
from pyclingo.program_elements import ProgramElement, render_body_terms
from pyclingo.scoping import body_global_variables

# What may be aggregated over: the same universe as aggregate tuple terms
type OPTIMIZATION_TERM_TYPE = Value | Expression | Predicate


# Matching, in order: quoted strings (with escapes), block comments, line
# comments — everything the optimization-token scan must NOT look inside
_INERT_TEXT = re.compile(r'"(?:[^"\\]|\\.)*"|%\*.*?\*%|%[^\n]*', re.DOTALL)
_OPTIMIZATION_TOKENS = re.compile(r"#minimize\b|#maximize\b|:~")


def raw_text_optimizes(text: str) -> bool:
    """
    Whether a raw ASP block makes the program an optimizing one: #minimize,
    #maximize, or a weak constraint (:~ — the same directive in disguise;
    gringo translates it to a minimize construct). Quoted strings and
    comments are stripped first so mentions there do not count.
    """
    return _OPTIMIZATION_TOKENS.search(_INERT_TEXT.sub("", text)) is not None


class WeakConstraint(ProgramElement):
    """
    A constraint that charges instead of forbidding: ":~ conditions. [W@P, T]".

    Semantically identical to a #minimize statement — gringo translates
    both to the same construct, and their tuples share the one global set —
    but the spelling states intent: penalize() reads as forbid() that
    negotiates. Constructed via ASPProgram.penalize(), not directly.
    """

    def __init__(
        self,
        conditions: tuple[Term, ...],
        weight: int | OPTIMIZATION_TERM_TYPE,
        tuple_terms: tuple[OPTIMIZATION_TERM_TYPE, ...] | None,
        priority: int,
    ) -> None:
        if isinstance(weight, int):
            weight = Number(weight)
        if isinstance(weight, String):
            raise TypeError("Weak-constraint weight must be integer-valued, got a String")
        if not isinstance(weight, (Value, Expression)):
            raise TypeError(f"Weak-constraint weight must be an int, Value, or Expression, got {type(weight).__name__}")
        if tuple_terms is None:
            # Per-match charging by default: the tuple gets the conditions'
            # global variables, spelled out in the render. gringo's bare
            # tuple collapses every match to ONE charge (the ASP-Core-2
            # standard specifies this implicit extension; gringo omits it,
            # so we write it explicitly). Pass terms=[] to collapse on
            # purpose.
            names = sorted(body_global_variables(list(conditions)))
            tuple_terms = tuple(Variable(name) for name in names)
        for term in tuple_terms:
            if not isinstance(term, (Value, Expression, Predicate)):
                raise TypeError(
                    f"Weak-constraint tuple terms must be Values, Expressions, or Predicates, got {type(term).__name__}"
                )
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise TypeError(f"Weak-constraint priority must be an int, got {type(priority).__name__}")
        if not conditions:
            raise ValueError("A weak constraint requires at least one condition")
        # The conditions form a RULE BODY: everything forbid() accepts is
        # legal here, validated the same way (a Choice raises its own
        # teaching error about body braces)
        for cond in conditions:
            if not isinstance(cond, Term):
                raise TypeError(f"Weak-constraint conditions must be Terms, got {type(cond).__name__}")
            cond.validate_in_context(is_in_head=False)

        self._priority = priority
        self._targets: tuple[Value | Expression | Predicate, ...] = (weight, *tuple_terms)
        self._conditions = list(conditions)

    @property
    def targets(self) -> tuple[Value | Expression | Predicate, ...]:
        """The weight followed by the tuple terms."""
        return self._targets

    @property
    def conditions(self) -> list[Term]:
        """The body (a defensive copy)."""
        return self._conditions.copy()

    def freeze(self) -> None:
        for target in self._targets:
            target.freeze()
        for cond in self._conditions:
            cond.freeze()

    def render(self) -> str:
        weight_str = self._targets[0].render()
        if self._priority != 0:
            weight_str = f"{weight_str}@{self._priority}"
        tuple_str = ", ".join([weight_str, *(term.render() for term in self._targets[1:])])
        return f":~ {render_body_terms(self._conditions)}. [{tuple_str}]"

    def collect_defined_constants(self) -> set[str]:
        constants: set[str] = set()
        for term in (*self._targets, *self._conditions):
            constants.update(term.collect_defined_constants())
        return constants

    def collect_predicate_signs(self) -> set[AtomSign]:
        # The body holds atoms; weight and tuple terms sit in argument
        # positions — demote their predicate occurrences to non-atoms
        signs: set[AtomSign] = set()
        for target in self._targets:
            signs.update((predicate, negated, False) for predicate, negated, _ in target.collect_predicate_signs())
        for cond in self._conditions:
            signs.update(cond.collect_predicate_signs())
        return signs


class Optimization(StrEnum):
    """Which way the total weight is preferred; values are the directive names."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class OptimizationDirective(ProgramElement):
    """
    One #minimize or #maximize statement with a single weighted element.

    Constructed via ASPProgram.minimize()/maximize(), not directly. The
    weight is the quantity summed over distinct ground tuples; tuple terms
    disambiguate contributions exactly as in #sum (two islands of size 3
    need the island in the tuple, or they collapse to one contribution).
    """

    def __init__(
        self,
        optimization: Optimization,
        weight: int | OPTIMIZATION_TERM_TYPE,
        tuple_terms: tuple[OPTIMIZATION_TERM_TYPE, ...],
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None,
        priority: int,
    ) -> None:
        if isinstance(weight, int):
            weight = Number(weight)
        if isinstance(weight, String):
            raise TypeError("Optimization weight must be integer-valued, got a String")
        if not isinstance(weight, (Value, Expression)):
            raise TypeError(f"Optimization weight must be an int, Value, or Expression, got {type(weight).__name__}")
        for term in tuple_terms:
            if not isinstance(term, (Value, Expression, Predicate)):
                raise TypeError(
                    f"Optimization tuple terms must be Values, Expressions, or Predicates, got {type(term).__name__}"
                )
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise TypeError(f"Optimization priority must be an int, got {type(priority).__name__}")

        self._optimization = optimization
        self._weight = weight
        self._priority = priority
        self._element = ConditionedElement((weight, *tuple_terms), condition, "optimization")

    @property
    def optimization(self) -> Optimization:
        return self._optimization

    @property
    def element(self) -> ConditionedElement:
        return self._element

    def render(self) -> str:
        directive = f"#{self._optimization.value}"
        targets = self._element.targets
        weight_str = targets[0].render()
        if self._priority != 0:
            weight_str = f"{weight_str}@{self._priority}"
        parts = [weight_str, *(term.render() for term in targets[1:])]
        element_str = ", ".join(parts)
        if conditions := self._element.conditions:
            element_str += " : " + ", ".join(cond.render() for cond in conditions)
        return f"{directive}{{ {element_str} }}."

    def collect_defined_constants(self) -> set[str]:
        return self._element.collect_defined_constants()

    def collect_predicate_signs(self) -> set[AtomSign]:
        # Conditions hold atoms; the weight and tuple terms sit in argument
        # positions — demote their predicate occurrences to non-atoms
        signs: set[AtomSign] = set()
        for target in self._element.targets:
            signs.update((predicate, negated, False) for predicate, negated, _ in target.collect_predicate_signs())
        for cond in self._element.conditions:
            signs.update(cond.collect_predicate_signs())
        return signs
