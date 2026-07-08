"""
Segment: a named block of program elements that is also an authoring
surface, and When: the pending context its when() returns.

Every statement verb lives here, spoken from a segment; ASPProgram's
verbs delegate to its default segment. fact() adds grounded atoms or a
bare choice rule. when(*conditions) holds the conditions and completes
with exactly one closer, which adds the conditions as the rule body:
derive (a rule head — an atom or a choice), require (a comparison the
body must satisfy), forbid (extra body literals that must not all
hold), or penalize (the same as a weak constraint). forbid, require,
and penalize also exist as flat verbs with no conditions.

Some verbs are readability sugar over forbid: require(cmp) is
forbid(cmp.inverse()), and when(*conds).forbid(*extra) renders
identically to flat forbid(*conds, *extra) — the split just names which
part is the situation and which is the violation.
"""

from collections.abc import Iterator, Sequence

from pyclingo.choice import Choice
from pyclingo.conditioned_element import CONDITION_TYPE
from pyclingo.core import AtomSign, Comparison, Pool, Term
from pyclingo.optimization import (
    OPTIMIZATION_TERM_TYPE,
    Optimization,
    OptimizationDirective,
    WeakConstraint,
)
from pyclingo.predicate import PREDICATE_CLASS_TYPE, Predicate
from pyclingo.program_elements import BlankLine, Comment, ProgramElement, RawASP, Rule
from pyclingo.scoping import validate_optimization_element, validate_weak_constraint


class Segment:
    """
    One named block of program elements, rendered under its header, with
    the full set of statement verbs.

    A program's add_segment pre-declares a named segment, or attaches one
    built standalone — the program holds the object you gave it, so
    statements through any handle are visible. program["name"] reads a
    segment back (KeyError if absent) and program["name"] = segment
    assigns one; the default segment is created on first use, and every
    other segment must be added with add_segment.

    allow_singletons switches off the singleton-variable lint for
    statements made through this segment (a variable used exactly once is
    rejected as a likely typo); segments a program creates inherit the
    program's setting.
    """

    def __init__(self, name: str, allow_singletons: bool = False) -> None:
        self._name = self.validate_name(name)
        self._elements: list[ProgramElement] = []
        self._check_singletons = not allow_singletons
        self._pending: list[When] = []

    @staticmethod
    def validate_name(name: str) -> str:
        """The name, exactly as given; rejects empty or multi-line ones."""
        if not isinstance(name, str):
            raise TypeError(f"Segment name must be a string, got {type(name).__name__}")
        if not name.strip():
            raise ValueError("Segment names cannot be empty")
        if "\n" in name or "\r" in name:
            raise ValueError("Segment names must be single-line (they render as section comments)")
        return name

    @property
    def name(self) -> str:
        """The segment's name."""
        return self._name

    def append(self, element: ProgramElement) -> None:
        """Add an element to the end of the segment."""
        self._elements.append(element)

    def __len__(self) -> int:
        return len(self._elements)

    def __iter__(self) -> Iterator[ProgramElement]:
        return iter(self._elements)

    # ---- statement verbs ----

    def fact(self, *facts: Predicate | Choice) -> None:
        """
        Add unconditional statements: grounded facts, or bare choice rules
        like { a(1..3) } whose element variables are local.
        """
        if not facts:
            raise ValueError("fact() requires at least one statement")
        for statement in facts:
            if not isinstance(statement, (Predicate, Choice)):
                raise TypeError(
                    f"fact() arguments must be Predicate or Choice instances, got {type(statement).__name__}"
                )
            if isinstance(statement, Predicate) and not statement.is_grounded:
                variables = ", ".join(sorted(statement.collect_variables()))
                raise ValueError(
                    f"fact() requires grounded predicates, but {statement.render()} contains "
                    f"variable(s) {variables}. Use when(*conditions).derive(...) to derive predicates."
                )
        for statement in facts:
            rule = Rule(head=statement, check_singletons=self._check_singletons)
            self.append(rule)

    def when(self, *conditions: Term) -> When:
        """
        Hold the conditions as a rule body, to be completed by exactly one
        of .derive/.require/.forbid/.penalize. Returns a pending context; a
        when() left unclosed fails at render.
        """
        if not conditions:
            raise ValueError(
                "when() requires at least one condition; for unconditional statements use fact() or require() directly"
            )
        for condition in conditions:
            if not isinstance(condition, Term):
                raise TypeError(f"when() conditions must be Terms, got {type(condition).__name__}")
        return When(self, conditions)

    def forbid(self, *conditions: Term) -> None:
        """Forbid the combination: no answer set may satisfy all conditions."""
        if not conditions:
            raise ValueError("forbid() requires at least one condition")
        for condition in conditions:
            if not isinstance(condition, Term):
                raise TypeError(f"forbid() conditions must be Terms, got {type(condition).__name__}")
        rule = Rule(body=list(conditions), check_singletons=self._check_singletons)
        self.append(rule)

    def require(self, *comparison: Term) -> None:
        """
        Require that a comparison holds in every answer set. Takes exactly
        one Comparison; a conditional requirement is spelled
        when(*conditions).require(comparison). Sugar for forbidding the
        inverse comparison.
        """
        target = _single_required_comparison(comparison)
        rule = Rule(body=[target.inverse()], check_singletons=self._check_singletons)
        self.append(rule)

    def penalize(
        self,
        *conditions: Term,
        weight: int | OPTIMIZATION_TERM_TYPE = 1,
        terms: Sequence[OPTIMIZATION_TERM_TYPE] | None = None,
        priority: int = 0,
    ) -> None:
        """
        A forbid() that charges instead of forbidding: each ground match of
        the conditions adds weight to the cost, and optimize() prefers
        answer sets paying least. Renders as a weak constraint,
        ":~ conditions. [weight@priority, terms]" — semantically identical
        to minimize() (one shared tuple set; duplicate tuples count once),
        so the spelling is intent: penalize() for soft constraints,
        minimize() for objectives.

        By default each ground match is charged separately: the tuple gets
        the conditions' variables, written out in the render. Pass terms=
        to charge by a different identity — terms=[] deliberately collapses
        EVERY match into one charge (gringo's own bare-tuple semantics).
        Every weight/terms variable must be bound by the conditions.
        """
        weak = WeakConstraint(conditions, weight, tuple(terms) if terms is not None else None, priority)
        validate_weak_constraint(
            weak.targets, list(weak.conditions), weak.render(), check_singletons=self._check_singletons
        )
        weak.freeze()
        self.append(weak)

    def minimize(
        self,
        weight: int | OPTIMIZATION_TERM_TYPE,
        *tuple_terms: OPTIMIZATION_TERM_TYPE,
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None = None,
        priority: int = 0,
    ) -> None:
        """
        Add a #minimize statement: among the answer sets, prefer those
        where the total weight is smallest. The weight is summed over
        DISTINCT ground tuples, so include identifying terms after it
        exactly as in a #sum tuple:

            minimize(Size, C, condition=island(loc=C, size=Size))

        renders "#minimize{ Size, C : island(C, Size) }." — without C, two
        same-sized islands would collapse to one contribution. priority
        stacks objectives lexicographically (higher decided first,
        rendered W@P); priorities are ordinal keys and gaps are free.
        All statements at a priority share ONE tuple set: duplicate
        tuples count once, distinct tuples sum.

        Every variable must be bound by the element's own conditions — this
        directive has no rule body. Optimization changes how the program
        must be solved; see optimize().
        """
        self._add_optimization(Optimization.MINIMIZE, weight, tuple_terms, condition, priority)

    def maximize(
        self,
        weight: int | OPTIMIZATION_TERM_TYPE,
        *tuple_terms: OPTIMIZATION_TERM_TYPE,
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None = None,
        priority: int = 0,
    ) -> None:
        """
        Add a #maximize statement: prefer answer sets with the LARGEST
        total weight. Exactly minimize() with the preference flipped
        (clingo reports the cost of a maximization as a negated sum). See
        minimize() for the tuple-distinctness and priority rules.
        """
        self._add_optimization(Optimization.MAXIMIZE, weight, tuple_terms, condition, priority)

    def _add_optimization(
        self,
        sense: Optimization,
        weight: int | OPTIMIZATION_TERM_TYPE,
        tuple_terms: tuple[OPTIMIZATION_TERM_TYPE, ...],
        condition: CONDITION_TYPE | list[CONDITION_TYPE] | None,
        priority: int,
    ) -> None:
        directive = OptimizationDirective(sense, weight, tuple_terms, condition, priority)
        validate_optimization_element(directive.element, directive.render(), check_singletons=self._check_singletons)
        directive.element.freeze()
        self.append(directive)

    def raw_asp(self, text: str, predicates: Sequence[PREDICATE_CLASS_TYPE] = ()) -> None:
        """
        Add a verbatim block of ASP text: the escape hatch for constructs
        pyclingo does not model.

        Declare any predicates the block produces via predicates so that show
        directives cover them and solutions round-trip into typed instances.
        A declaration covers the POSITIVE sign's visibility; raw text that
        derives classically negated atoms (-p) needs its own visibility
        channel — a raw "#show -p/n." line, or show_when with a negated
        head — or those atoms stay silently absent from output.
        """
        if not isinstance(text, str):
            raise TypeError(f"raw_asp() text must be a string, got {type(text).__name__}")
        self.append(RawASP(text, predicates))

    def comment(self, text: str) -> None:
        """Add a comment."""
        self.append(Comment(text))

    def blank_line(self) -> None:
        """Add a blank line for formatting."""
        self.append(BlankLine())

    def section(self, title: str) -> None:
        """Add a blank line and title comment as a section header."""
        self.blank_line()
        self.comment(title)

    # ---- rendering and walking ----

    def render(self, with_header: bool) -> str:
        """
        Render the segment's elements, one per line. With with_header, the
        elements are framed by a blank line, a "% ===== name =====" section
        comment, and one blank line — any blank the content already opens
        with is absorbed, so the gap after the header is always exactly one.
        Raises if any when() in this segment was never completed.
        """
        self.check_pending()
        lines = [element.render() for element in self._elements]
        if with_header:
            while lines and lines[0] == "":
                lines.pop(0)
            lines = ["", f"% ===== {self._name} =====", "", *lines]
        return "\n".join(lines)

    def check_pending(self) -> None:
        """Raise if any when() on this segment is still awaiting its closer."""
        if self._pending:
            listing = "; ".join(f"when({', '.join(c.render() for c in w.conditions)})" for w in self._pending)
            raise ValueError(
                f"Segment '{self._name}' has incomplete when() statements: {listing}. "
                f"Complete each with .derive/.require/.forbid/.penalize."
            )

    def collect_predicate_signs(self) -> set[AtomSign]:
        """(class, negated, is_atom) occurrences across the segment's elements."""
        signs: set[AtomSign] = set()
        for element in self._elements:
            signs.update(element.collect_predicate_signs())
        return signs

    def collect_defined_constants(self) -> set[str]:
        """All defined constant names used in the segment's elements."""
        constants: set[str] = set()
        for element in self._elements:
            constants.update(element.collect_defined_constants())
        return constants


class When:
    """
    The pending context returned by when(): conditions awaiting a closer.
    Exactly one of derive, require, forbid, or penalize completes it, using
    the conditions as the rule body; completing it twice raises, and a When
    left incomplete fails the render.
    """

    def __init__(self, segment: Segment, conditions: tuple[Term, ...]) -> None:
        self._segment = segment
        self._conditions = conditions
        self._completed_by: str | None = None
        segment._pending.append(self)

    @property
    def conditions(self) -> tuple[Term, ...]:
        """The held conditions."""
        return self._conditions

    def _complete(self, closer: str, element: ProgramElement) -> None:
        # The element is fully built (and validated) before the context
        # resolves, so a rejected statement leaves the When retryable
        self._guard(closer)
        self._completed_by = closer
        self._segment._pending.remove(self)
        self._segment.append(element)

    def _guard(self, closer: str) -> None:
        if self._completed_by is not None:
            raise RuntimeError(
                f"This when() was already completed with .{self._completed_by}(); "
                f"it takes exactly one statement — call when() again for another"
            )

    def derive(self, head: Term) -> None:
        """
        Add head with the conditions as its body: "head :- conditions.". The
        head is any rule head — an atom or a Choice.
        """
        if not isinstance(head, Term):
            raise TypeError(f"derive() head must be a Term, got {type(head).__name__}")
        self._guard("derive")
        rule = Rule(head=head, body=list(self._conditions), check_singletons=self._segment._check_singletons)
        self._complete("derive", rule)

    def require(self, *comparison: Term) -> None:
        """
        Require the comparison to hold under the conditions. Takes exactly
        one Comparison; sugar for forbid(*conditions, comparison.inverse()).
        """
        target = _single_required_comparison(comparison)
        self._guard("require")
        rule = Rule(
            body=[*self._conditions, target.inverse()],
            check_singletons=self._segment._check_singletons,
        )
        self._complete("require", rule)

    def forbid(self, *violation: Term) -> None:
        """
        Forbid the conditions together with the violation literals: renders
        identically to flat forbid(*conditions, *violation). The split is
        sugar — it names which literals are the situation and which are the
        violation. Takes at least one violation term.
        """
        if not violation:
            raise ValueError(
                "when(...).forbid() takes at least one violation term; to forbid the "
                "conditions themselves, use the flat forbid(*conditions)"
            )
        for term in violation:
            if not isinstance(term, Term):
                raise TypeError(f"forbid() violation terms must be Terms, got {type(term).__name__}")
        self._guard("forbid")
        rule = Rule(
            body=[*self._conditions, *violation],
            check_singletons=self._segment._check_singletons,
        )
        self._complete("forbid", rule)

    def penalize(
        self,
        *violation: Term,
        weight: int | OPTIMIZATION_TERM_TYPE = 1,
        terms: Sequence[OPTIMIZATION_TERM_TYPE] | None = None,
        priority: int = 0,
    ) -> None:
        """
        Charge for the conditions together with the violation instead of
        forbidding them: a weak constraint over the same body forbid() would
        reject. Takes at least one violation term; weight/terms/priority as
        in the flat penalize().
        """
        if not violation:
            raise ValueError(
                "when(...).penalize() takes at least one violation term; to charge for the "
                "conditions themselves, use the flat penalize(*conditions)"
            )
        for term in violation:
            if not isinstance(term, Term):
                raise TypeError(f"penalize() violation terms must be Terms, got {type(term).__name__}")
        self._guard("penalize")
        weak = WeakConstraint(
            (*self._conditions, *violation), weight, tuple(terms) if terms is not None else None, priority
        )
        validate_weak_constraint(
            weak.targets, list(weak.conditions), weak.render(), check_singletons=self._segment._check_singletons
        )
        weak.freeze()
        self._complete("penalize", weak)


def _single_required_comparison(args: tuple[Term, ...]) -> Comparison:
    """Exactly one Comparison, with teaching errors for every other shape."""
    if len(args) != 1:
        raise TypeError(
            "require() takes exactly one Comparison; conditions go in when(): when(*conditions).require(comparison)"
        )
    target = args[0]
    if not isinstance(target, Comparison):
        raise TypeError(
            f"require() takes a Comparison, got {type(target).__name__}. To make "
            f"a predicate hold, derive it: when(*conditions).derive(...)."
        )
    if isinstance(target.right_term, Pool):
        raise ValueError(
            "require() cannot invert a pool comparison: pools expand disjunctively, "
            "so 'X != (2;3)' is true for every X. Write the domain restriction as a "
            "positive body condition instead."
        )
    return target
