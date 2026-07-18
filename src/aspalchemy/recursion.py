"""
Recursion analysis: the recursive components of a program's predicate
dependency graph, with the statements grounding inside each
component's fixpoint.

ASPProgram's recursion_profile()/analyze_recursion() are thin entrypoints
over this module. The analysis is static — no grounding is performed — so
it answers "what will ground recursively?" before any ground() is paid.
Components are the strongly connected components of the FULL dependency
graph, positive and default-negated edges together — the textbook object
of stratification. A stratified (positive-only) component grounds as one
gringo fixpoint: its statements are re-evaluated across the iteration,
and a derivation there that need not feed the recursion (restatable as a
requirement) is the classic slow-grounding finding. An UNSTRATIFIED
component's cycle passes through 'not': the rules are strongly circular
— defined in terms of their own absence — so gringo cannot settle them
and clasp is relegated to guess-and-check search. A well-shaped encoding
is a tower (base data, then choices, then rules on top, each stratum
negating only what is already settled below); an unstratified component
means the tower folded back on itself, the solving is expensive, and
you probably don't want it. raw_asp text is deliberately ignored:
its predicates= declarations give existence, not structure.
"""

import itertools
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from aspalchemy.aggregates import Aggregate
from aspalchemy.choice import Choice
from aspalchemy.conditional_literal import ConditionalLiteral
from aspalchemy.core import Comparison, DefaultNegation, Term
from aspalchemy.predicate import Predicate
from aspalchemy.program_elements import Rule
from aspalchemy.source_location import SourceLocation

type Signature = tuple[str, int]


@dataclass(frozen=True)
class RecursiveComponent:
    """
    One recursive component of the program's predicate dependency
    graph (positive and default-negated edges together): signatures
    whose derivations depend on each other, directly or mutually.
    statements holds the (rendered text, authoring location) of every
    rule inside the component's cycle — head in the component and at
    least one body dependency in it — in program order. A rule that
    merely seeds the component (no body dependency inside it) is not
    listed.

    A stratified component (unstratified=False) recurses positively
    only: gringo grounds it as one fixpoint, re-evaluating its
    statements across the iteration — the first place to look when a
    recursive grounding is slow. unstratified=True means the cycle
    passes through default negation — a 'not p' whose p is in the
    component — making the rules strongly circular: gringo cannot
    settle them, solving degrades to guess-and-check search, and in a
    well-shaped encoding it is nearly always an accident. You probably
    don't want this.
    """

    signatures: tuple[Signature, ...]
    statements: tuple[tuple[str, SourceLocation | None], ...]  # in program order
    unstratified: bool


class _Dependencies:
    """One rule's head signatures and its positive/negated body signatures."""

    def __init__(self) -> None:
        self.heads: set[Signature] = set()
        self.positive: set[Signature] = set()
        self.negative: set[Signature] = set()

    def collect(self, term: Term, *, head: bool = False, negated: bool = False) -> None:
        """
        Walk a term structurally, recording predicate ATOMS (arguments are
        terms, not dependencies) and tracking default-negation context —
        the occurrence walk cannot supply it (its flag is the classical
        sign), and 'not p' is not a positive dependency.
        """
        if isinstance(term, DefaultNegation):
            self.collect(term.term, head=head, negated=True)
        elif isinstance(term, Choice):
            for element in term.elements:
                for target in element.targets:
                    self.collect(target, head=head, negated=negated)
                for condition in element.conditions:
                    self.collect(condition, negated=negated)
        elif isinstance(term, Aggregate):
            for element in term.elements:
                for condition in element.conditions:
                    self.collect(condition, negated=negated)
        elif isinstance(term, ConditionalLiteral):
            self.collect(term.head, head=head, negated=negated)
            for condition in term.condition:
                self.collect(condition, negated=negated)
        elif isinstance(term, Comparison):
            # Private on purpose: the operands are where body aggregates
            # live (N == Count(...)), and Comparison exposes no walk. Only
            # aggregate operands are walked — a compound Predicate operand
            # (C == Cell(X, ANY), a destructuring term equation) is
            # unification data, not an atom occurrence
            for operand in (term._left_term, term._right_term):
                if isinstance(operand, Aggregate):
                    self.collect(operand, negated=negated)
        elif isinstance(term, Predicate):
            name = type(term).get_name()
            if term.negated:
                name = f"-{name}"
            signature = (name, len(type(term).field_names()))
            if head:
                self.heads.add(signature)
            elif negated:
                self.negative.add(signature)
            else:
                self.positive.add(signature)


def _rule_dependencies(rule: Rule) -> _Dependencies:
    dependencies = _Dependencies()
    if rule.head is not None:
        dependencies.collect(rule.head, head=True)
    for term in rule.body:
        dependencies.collect(term)
    return dependencies


def recursion_profile(rules: Sequence[Rule]) -> tuple[RecursiveComponent, ...]:
    """
    The recursive components of the predicate dependency graph, largest
    first: for every rule, each body atom's signature — positive or
    default-negated — depends toward each head signature; Tarjan's
    algorithm finds the strongly connected components; a component is
    recursive when it has several signatures or a self-loop. A component
    whose cycle passes through negation reports unstratified=True (a
    negation-only cycle is not a grounding fixpoint, but it is the
    textbook unstratified shape and clasp resolves it by search).
    raw_asp text is invisible here.
    """
    dependencies = [_rule_dependencies(rule) for rule in rules]
    edges: dict[Signature, set[Signature]] = {}
    nodes: set[Signature] = set()
    for entry in dependencies:
        nodes.update(entry.heads)
        nodes.update(entry.positive)
        nodes.update(entry.negative)
        for body_signature in entry.positive | entry.negative:
            edges.setdefault(body_signature, set()).update(entry.heads)

    # Iterative Tarjan
    index_of: dict[Signature, int] = {}
    low: dict[Signature, int] = {}
    on_stack: set[Signature] = set()
    stack: list[Signature] = []
    components: list[frozenset[Signature]] = []
    counter = itertools.count()
    for root in sorted(nodes):
        if root in index_of:
            continue
        work: list[tuple[Signature, Iterator[Signature]]] = []
        index_of[root] = low[root] = next(counter)
        stack.append(root)
        on_stack.add(root)
        work.append((root, iter(sorted(edges.get(root, ())))))
        while work:
            node, successors = work[-1]
            advanced = False
            for successor in successors:
                if successor not in index_of:
                    index_of[successor] = low[successor] = next(counter)
                    stack.append(successor)
                    on_stack.add(successor)
                    work.append((successor, iter(sorted(edges.get(successor, ())))))
                    advanced = True
                    break
                if successor in on_stack:
                    low[node] = min(low[node], index_of[successor])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index_of[node]:
                collected: set[Signature] = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    collected.add(member)
                    if member == node:
                        break
                components.append(frozenset(collected))

    profile: list[RecursiveComponent] = []
    for component in components:
        self_looped = any(
            entry.heads & component and (entry.positive | entry.negative) & component and len(component) == 1
            for entry in dependencies
        )
        if len(component) < 2 and not self_looped:
            continue
        statements: list[tuple[str, SourceLocation | None]] = []
        unstratified = False
        for rule, entry in zip(rules, dependencies, strict=True):
            if not entry.heads & component:
                continue
            if entry.negative & component:
                unstratified = True
            if (entry.positive | entry.negative) & component:
                statements.append((rule.render(), rule.source_location))
        profile.append(
            RecursiveComponent(
                signatures=tuple(sorted(component)),
                statements=tuple(statements),
                unstratified=unstratified,
            )
        )
    profile.sort(key=lambda entry: (-len(entry.signatures), entry.signatures))
    return tuple(profile)


def analyze_recursion(profile: tuple[RecursiveComponent, ...]) -> str:
    """
    The recursion profile as prose: each recursive component's
    signatures, whether it is stratified, and the statements grounding
    inside its fixpoint — the rules gringo re-evaluates across the
    iteration, and the candidates to restate as requirements when they
    need not feed the recursion.
    """
    if not profile:
        return "Recursion profile: no recursive components"
    lines = [f"Recursion profile: {len(profile)} recursive component{'s' if len(profile) > 1 else ''}"]
    for entry in profile:
        names = " + ".join(f"{name}/{arity}" for name, arity in entry.signatures)
        marker = (
            " — UNSTRATIFIED: circular through 'not'; expensive to solve, probably unintended"
            if entry.unstratified
            else ""
        )
        lines.append(f"  {names}{marker}")
        for statement, location in entry.statements:
            origin = location.display() if location is not None else "unknown (source locations off)"
            shown = statement if len(statement) <= 80 else statement[:77] + "..."
            lines.append(f"    {shown}  — {origin}")
    return "\n".join(lines)
