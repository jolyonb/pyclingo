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
minimize()/maximize() tuples are the caller's, rendered exactly as
given; penalize()'s AUTO tuples carry a per-statement discriminator so
independent penalties never share tuples by accident (see
WeakConstraint).
"""

from enum import StrEnum

from pyclingo.conditioned_element import ConditionedElement, ConditionType
from pyclingo.core import (
    Expression,
    ExtremeConstant,
    Number,
    PredicateOccurrence,
    String,
    Term,
    Value,
    Variable,
)
from pyclingo.predicate import Predicate
from pyclingo.program_elements import ProgramElement, render_body_terms
from pyclingo.scoping import body_global_variables

# What may be aggregated over: the same universe as aggregate tuple terms
type OptimizationTermType = Value | Expression | Predicate


def _validated_weight(weight: int | OptimizationTermType, noun: str) -> Value | Expression:
    """The weight rules both constructs share; the noun keeps each error's spelling."""
    if isinstance(weight, int):
        weight = Number(weight)
    if isinstance(weight, String):
        raise TypeError(f"{noun} weight must be integer-valued, got a String")
    if isinstance(weight, ExtremeConstant):
        raise TypeError(f"{noun} weight must be integer-valued, got {weight.render()}")
    if not isinstance(weight, (Value, Expression)):
        raise TypeError(f"{noun} weight must be an int, Value, or Expression, got {type(weight).__name__}")
    return weight


def _validate_priority(priority: int, noun: str) -> None:
    """The priority rules both constructs share."""
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise TypeError(f"{noun} priority must be an int, got {type(priority).__name__}")
    if not -(2**31) <= priority < 2**31:
        raise ValueError(
            f"{noun} priority {priority} is outside clingo's integer range "
            f"[-2147483648, 2147483647]; clingo would silently wrap it, merging or "
            f"reordering objective tiers"
        )


def _weight_at_priority(weight: Term, priority: int) -> str:
    """Render W@P, with @0 elided so bare and explicit-zero spellings cannot diverge."""
    weight_str = weight.render()
    return f"{weight_str}@{priority}" if priority != 0 else weight_str


class WeakConstraint(ProgramElement):
    """
    A constraint that charges instead of forbidding: ":~ conditions. [W@P, T]".

    Semantically identical to a #minimize statement — gringo translates
    both to the same construct, and their tuples share the one global set —
    but the spelling states intent: penalize() reads as forbid() that
    negotiates. Constructed via ASPProgram.penalize(), not directly.

    Tuple identity is owned per the spelling: an AUTO tuple (terms omitted)
    means the library owns it — this statement, this match, charged once —
    so the program render adds a per-statement discriminator term
    ("weak-constraint-N") that keeps two statements' coinciding ground
    tuples from silently merging in the shared set. Explicit terms= means
    the caller owns the identity: rendered exactly as given, gringo's
    shared tuple-set semantics included.
    """

    def __init__(
        self,
        conditions: tuple[Term, ...],
        weight: int | OptimizationTermType,
        tuple_terms: tuple[OptimizationTermType, ...] | None,
        priority: int,
    ) -> None:
        weight = _validated_weight(weight, "Weak-constraint")
        # Checked after coercion so Number(-3) is caught the same as -3. A
        # negative weight is legal ASP but turns the penalty into a reward,
        # inverting the verb's name — almost certainly a sign flip
        if isinstance(weight, Number) and weight.value < 0:
            raise ValueError(
                f"penalize() charges a cost, but weight={weight.value} would reward the match "
                f"instead. To deliberately reward, use maximize() (or minimize() with a negative "
                f"weight) — the objective verbs say what they mean."
            )
        # An auto tuple delegates identity to the library; the program render
        # completes it with a per-statement discriminator (see the class
        # docstring). None until a program render assigns it.
        self._auto_tuple = tuple_terms is None
        self.discriminator: int | None = None
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
        _validate_priority(priority, "Weak-constraint")
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
    def auto_tuple(self) -> bool:
        """Whether the tuple was auto-built (terms omitted), so the program render adds a discriminator."""
        return self._auto_tuple

    @property
    def priority(self) -> int:
        return self._priority

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
        parts = [_weight_at_priority(self._targets[0], self._priority)]
        # The discriminator names this statement in the shared tuple set —
        # two auto-tupled statements over one domain must not merge charges.
        # Standalone renders (fragments, validation error text) have no
        # program-assigned ordinal and render the user's tuple bare.
        if self._auto_tuple and self.discriminator is not None:
            parts.append(f'"weak-constraint-{self.discriminator}"')
        parts.extend(term.render() for term in self._targets[1:])
        return f":~ {render_body_terms(self._conditions)}. [{', '.join(parts)}]"

    def collect_defined_constants(self) -> set[str]:
        constants: set[str] = set()
        for term in (*self._targets, *self._conditions):
            constants.update(term.collect_defined_constants())
        return constants

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        # The body holds atoms in this element's position; weight and tuple
        # terms sit in argument positions (data)
        occurrences: set[PredicateOccurrence] = set()
        for target in self._targets:
            occurrences.update(target.collect_predicate_occurrences(as_argument=True))
        for cond in self._conditions:
            occurrences.update(cond.collect_predicate_occurrences(as_argument=as_argument))
        return occurrences


class OptStrategy(StrEnum):
    """
    clasp's optimization strategy; values are the config spellings.

    BB (branch and bound, the default) descends from above: every
    emission is a solution, each better than the last — the anytime
    workflow. USC (unsatisfiable cores) proves from below: often
    dramatically faster on hard combinatorial optima, but its emission
    stream is sparse (frequently just the optimum), so best-so-far
    visibility degrades. Try USC whenever branch and bound stalls.
    """

    BB = "bb"
    USC = "usc"


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
        weight: int | OptimizationTermType,
        tuple_terms: tuple[OptimizationTermType, ...],
        condition: ConditionType | list[ConditionType] | None,
        priority: int,
    ) -> None:
        weight = _validated_weight(weight, "Optimization")
        for term in tuple_terms:
            if not isinstance(term, (Value, Expression, Predicate)):
                raise TypeError(
                    f"Optimization tuple terms must be Values, Expressions, or Predicates, got {type(term).__name__}"
                )
        _validate_priority(priority, "Optimization")

        self._optimization = optimization
        self._priority = priority
        self._element = ConditionedElement((weight, *tuple_terms), condition, "optimization")

    @property
    def optimization(self) -> Optimization:
        return self._optimization

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def element(self) -> ConditionedElement:
        return self._element

    def render(self) -> str:
        directive = f"#{self._optimization.value}"
        targets = self._element.targets
        parts = [_weight_at_priority(targets[0], self._priority), *(term.render() for term in targets[1:])]
        element_str = ", ".join(parts)
        if conditions := self._element.conditions:
            element_str += " : " + ", ".join(cond.render() for cond in conditions)
        return f"{directive}{{ {element_str} }}."

    def collect_defined_constants(self) -> set[str]:
        return self._element.collect_defined_constants()

    def collect_predicate_occurrences(self, *, as_argument: bool) -> set[PredicateOccurrence]:
        # Conditions hold atoms in this directive's position; the weight and
        # tuple terms sit in argument positions (data)
        occurrences: set[PredicateOccurrence] = set()
        for target in self._element.targets:
            occurrences.update(target.collect_predicate_occurrences(as_argument=True))
        for cond in self._element.conditions:
            occurrences.update(cond.collect_predicate_occurrences(as_argument=as_argument))
        return occurrences
