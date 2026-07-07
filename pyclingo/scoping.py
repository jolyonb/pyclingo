"""
Variable scoping analysis for rules: the machinery behind unsafe-variable
and singleton-variable validation.

The "binds" relation here deliberately OVER-APPROXIMATES gringo's: positive
literals bind all their variables under any operator, and an equality binds
one whole side once the other side is fully bound, regardless of the
expression's shape. Every rejection is therefore a certain gringo rejection
(no false positives); the cost is a few false negatives (e.g. X**2 = 9,
which gringo cannot invert) that fall back to clingo's own grounding error.
The probe-derived ground truth lives in tests/pyclingo/test_scoping.py.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pyclingo.aggregates import Aggregate
from pyclingo.choice import Choice
from pyclingo.conditional_literal import ConditionalLiteral
from pyclingo.core import AggregateBase, Comparison, DefaultNegation, ExplicitPool, Expression, Term, Variable
from pyclingo.predicate import Predicate

if TYPE_CHECKING:
    # Annotation-only upward reference: program_elements imports validate_rule
    # from here, so scoping cannot import Rule at runtime
    from pyclingo.program_elements import Rule

# An equality edge: if every variable on one side is bound, the other side
# becomes bound (and vice versa)
type EqualityEdge = tuple[frozenset[str], frozenset[str]]


@dataclass
class LocalScope:
    """One aggregate element, choice element, or conditional literal."""

    description: str  # for error messages, e.g. "#count element" or "choice element"
    target_counts: Counter[str] = field(default_factory=Counter)
    condition_counts: Counter[str] = field(default_factory=Counter)
    binders: set[str] = field(default_factory=set)
    equality_edges: list[EqualityEdge] = field(default_factory=list)
    # Choice elements without conditions expose their target variables
    # globally; aggregate targets must be bound by their own condition
    targets_are_global_without_condition: bool = False
    # Aggregate element tuples must not share variables with the rule's
    # globals: the tuple collapses to at most one element per ground instance
    is_aggregate_element: bool = False


@dataclass
class RuleScopes:
    """The complete variable-scoping picture of one rule."""

    head_counts: Counter[str] = field(default_factory=Counter)
    body_counts: Counter[str] = field(default_factory=Counter)  # global occurrences only
    global_binders: set[str] = field(default_factory=set)
    equality_edges: list[EqualityEdge] = field(default_factory=list)
    anonymous_in_head: bool = False
    local_scopes: list[LocalScope] = field(default_factory=list)
    # (variable, element description) pairs where an aggregate tuple shares a
    # variable with the rule's globals — valid clingo with collapsed semantics
    globals_in_aggregate_tuples: list[tuple[str, str]] = field(default_factory=list)

    def global_occurrences(self) -> Counter[str]:
        return self.head_counts + self.body_counts


def _variables_of(term: Term) -> set[str]:
    """Named variables of a term (the anonymous _ is never counted)."""
    return {name for name in term.collect_variables() if name != "_"}


def _occurrences(term: Term) -> Counter[str]:
    """
    Count every occurrence of each named variable — edge(X, X) counts X
    twice, so it is correctly not a singleton. Aggregates never reach here;
    callers route them to _analyze_aggregate for local-scope treatment.
    """
    counts: Counter[str] = Counter()
    if isinstance(term, Variable):
        if not term.is_anonymous:
            counts[term.name] += 1
    elif isinstance(term, Predicate):
        for arg in term.arguments:
            counts.update(_occurrences(arg))
    elif isinstance(term, Expression):
        if term.first_term is not None:
            counts.update(_occurrences(term.first_term))
        counts.update(_occurrences(term.second_term))
    elif isinstance(term, Comparison):
        for side in (term.left_term, term.right_term):
            if not isinstance(side, AggregateBase):
                counts.update(_occurrences(side))
    elif isinstance(term, DefaultNegation):
        counts.update(_occurrences(term.term))
    elif isinstance(term, ExplicitPool):
        for element in term.elements:
            counts.update(_occurrences(element))
    # Constants and range pools (grounded bounds) contain no variables
    return counts


def _count_variables(term: Term, counts: Counter[str]) -> None:
    counts.update(_occurrences(term))


def _bind_fixpoint(binders: set[str], edges: list[EqualityEdge]) -> set[str]:
    """Propagate bindings across equality edges until nothing changes."""
    bound = set(binders)
    changed = True
    while changed:
        changed = False
        for left, right in edges:
            if left and left <= bound and not right <= bound:
                bound |= right
                changed = True
            if right and right <= bound and not left <= bound:
                bound |= left
                changed = True
            # An empty side means the other side is bound unconditionally
            # (e.g. N = 1..3, or N = #count{ ... } whose variables are all local)
            if not left and not right <= bound:
                bound |= right
                changed = True
            if not right and not left <= bound:
                bound |= left
                changed = True
    return bound


def _analyze_comparison(comparison: Comparison, scopes: RuleScopes, counts: Counter[str]) -> None:
    """
    A body equality contributes a binding edge between its sides; any
    comparison counts its global variables. Aggregates inside comparisons
    become local scopes, and only their global-side variables join the edge.
    """
    side_vars: list[frozenset[str]] = []
    for term in (comparison.left_term, comparison.right_term):
        if isinstance(term, Aggregate):
            side_vars.append(frozenset(_analyze_aggregate(term, scopes)))
        else:
            _count_variables(term, counts)
            side_vars.append(frozenset(_variables_of(term)))

    if comparison.is_equality:
        scopes.equality_edges.append((side_vars[0], side_vars[1]))


def _analyze_aggregate(aggregate: Aggregate, scopes: RuleScopes) -> set[str]:
    """
    Analyze an aggregate's elements as local scopes. Returns the aggregate's
    GLOBAL variables (those also occurring outside constructs are resolved
    later; structurally, aggregates expose nothing globally themselves).
    """
    for element in aggregate.elements:
        scope = LocalScope(description=f"{aggregate.AGGREGATE_TYPE.value} element", is_aggregate_element=True)
        for target in element.targets:
            _count_variables(target, scope.target_counts)
        for condition in element.conditions:
            _analyze_local_condition(condition, scope)
        scopes.local_scopes.append(scope)
    return set()


def _analyze_local_condition(condition: Term, scope: LocalScope) -> None:
    """A condition inside an aggregate/choice element or conditional literal."""
    if isinstance(condition, Predicate):
        scope.binders |= _variables_of(condition)
        _count_variables(condition, scope.condition_counts)
    elif isinstance(condition, DefaultNegation):
        _count_variables(condition, scope.condition_counts)
    elif isinstance(condition, Comparison):
        sides = []
        for term in (condition.left_term, condition.right_term):
            _count_variables(term, scope.condition_counts)
            sides.append(frozenset(_variables_of(term)))
        if condition.is_equality:
            scope.equality_edges.append((sides[0], sides[1]))
    else:  # pragma: no cover - construction-time validation prevents this
        _count_variables(condition, scope.condition_counts)


def _analyze_negated_body_term(negation: DefaultNegation, scopes: RuleScopes) -> None:
    """
    A negated body literal: its variables count globally and bind nothing;
    an aggregate inside a negated comparison keeps its own local scopes
    (its element variables are not the rule's problem). No equality edges:
    a negated equality does not bind (probed).
    """
    inner = negation.term
    if isinstance(inner, DefaultNegation):  # not not X
        _analyze_negated_body_term(inner, scopes)
    elif isinstance(inner, Comparison):
        for side in (inner.left_term, inner.right_term):
            if isinstance(side, Aggregate):
                _analyze_aggregate(side, scopes)
            else:
                _count_variables(side, scopes.body_counts)
    else:
        _count_variables(inner, scopes.body_counts)


def analyze(head: Term | None, body: list[Term]) -> RuleScopes:
    """Build the RuleScopes for a rule's head and body terms."""
    scopes = RuleScopes()

    # --- head ---
    if isinstance(head, Predicate):
        if "_" in head.collect_variables():
            scopes.anonymous_in_head = True
        _count_variables(head, scopes.head_counts)
    elif isinstance(head, Comparison):
        # A comparison head forces the equality; all its variables are global
        # and need body binding (probed)
        for side in (head.left_term, head.right_term):
            if "_" in side.collect_variables():
                scopes.anonymous_in_head = True
            _count_variables(side, scopes.head_counts)
    elif isinstance(head, Choice):
        for element in head.elements:
            target = element.targets[0]  # choice elements have exactly one target
            if "_" in target.collect_variables():
                scopes.anonymous_in_head = True
            scope = LocalScope(description="choice element", targets_are_global_without_condition=True)
            _count_variables(target, scope.target_counts)
            for condition in element.conditions:
                _analyze_local_condition(condition, scope)
            scopes.local_scopes.append(scope)
        # Cardinality bound variables are global and need binding (probed)
        for bound in (head.min_cardinality, head.max_cardinality):
            if isinstance(bound, Variable) and not bound.is_anonymous:
                scopes.head_counts[bound.name] += 1

    # --- body ---
    for term in body:
        if isinstance(term, Predicate):
            scopes.global_binders |= _variables_of(term)
            _count_variables(term, scopes.body_counts)
        elif isinstance(term, DefaultNegation):
            # Negated literals count globally and bind nothing (probed)
            _analyze_negated_body_term(term, scopes)
        elif isinstance(term, Comparison):
            _analyze_comparison(term, scopes, scopes.body_counts)
        elif isinstance(term, ConditionalLiteral):
            scope = LocalScope(description="conditional literal", targets_are_global_without_condition=True)
            _count_variables(term.head, scope.target_counts)
            for condition in term.condition:
                _analyze_local_condition(condition, scope)
            scopes.local_scopes.append(scope)

    return scopes


def _resolve_localities(scopes: RuleScopes) -> None:
    """
    A construct variable is local only if it does not occur at rule level
    outside constructs; otherwise its occurrences count globally (probed:
    the Size == Count(Cell, condition=Region(loc=Cell, anchor=AnchorCell))
    pattern — Cell is local, AnchorCell is global). Construct targets with
    no supporting condition are global for choice elements and conditional
    literals (probed), but a safety error for aggregate elements — that
    case is left in the local scope for the safety check to catch.
    """
    global_names = set(scopes.global_occurrences())

    for scope in scopes.local_scopes:
        if scope.is_aggregate_element:
            for name in scope.target_counts:
                if name in global_names:
                    scopes.globals_in_aggregate_tuples.append((name, scope.description))
        for counter in (scope.target_counts, scope.condition_counts):
            for name in [n for n in counter if n in global_names]:
                scopes.body_counts[name] += counter.pop(name)
                scope.binders.discard(name)

        if scope.targets_are_global_without_condition:
            # Target variables with no occurrence in the condition are global
            # (choice element without condition; CL head var not in condition)
            condition_names = set(scope.condition_counts)
            for name in [n for n in scope.target_counts if n not in condition_names]:
                scopes.body_counts[name] += scope.target_counts.pop(name)


def validate_rule(head: Term | None, body: list[Term], rule: str | Rule) -> None:
    """
    Raise ValueError for unsafe or singleton variables, at rule construction
    time — the traceback lands on the line that built the bad rule.

    `rule` provides the text for error messages: pass the Rule itself (or
    anything with render()), and it is rendered only when an error actually
    needs it — the happy path never pays for the string.
    """

    def rule_text() -> str:
        return rule if isinstance(rule, str) else rule.render()

    scopes = analyze(head, body)
    _resolve_localities(scopes)

    if scopes.anonymous_in_head:
        raise ValueError(f"The anonymous variable '_' cannot appear in a rule head (unsafe): {rule_text()}")

    if scopes.globals_in_aggregate_tuples:
        listing = "; ".join(f"{name} in {description}" for name, description in scopes.globals_in_aggregate_tuples)
        raise ValueError(
            f"Aggregate tuple shares variable(s) with the rest of the rule ({listing}): {rule_text()}\n"
            f"With the variable fixed by the rule, the aggregate's element set collapses "
            f"to at most one element per ground instance — almost never the intent. "
            f"Use a fresh variable inside the aggregate."
        )

    bound = _bind_fixpoint(scopes.global_binders, scopes.equality_edges)
    unsafe = sorted(set(scopes.global_occurrences()) - bound)
    if unsafe:
        names = ", ".join(unsafe)
        raise ValueError(
            f"Unsafe variable(s) {names} in rule: {rule_text()}\n"
            f"Every variable must be bound by a positive body literal "
            f"(or an equality with something bound)."
        )

    for scope in scopes.local_scopes:
        local_bound = _bind_fixpoint(scope.binders | bound, scope.equality_edges)
        local_unsafe = sorted((set(scope.target_counts) | set(scope.condition_counts)) - local_bound)
        if local_unsafe:
            names = ", ".join(local_unsafe)
            raise ValueError(
                f"Unsafe local variable(s) {names} in {scope.description} of rule: {rule_text()}\n"
                f"Local variables must be bound by a positive condition inside "
                f"the same element."
            )

    singletons = sorted(
        [name for name, count in scopes.global_occurrences().items() if count == 1]
        + [
            name
            for scope in scopes.local_scopes
            for name, count in (scope.target_counts + scope.condition_counts).items()
            if count == 1
        ]
    )
    if singletons:
        names = ", ".join(singletons)
        raise ValueError(
            f"Singleton variable(s) {names} in rule: {rule_text()}\n"
            f"A variable used exactly once is usually a typo; use ANY for an "
            f"intentional don't-care."
        )
