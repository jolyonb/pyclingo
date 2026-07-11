"""
Segment: a named block of program elements that is also an authoring
surface, and When: the pending context its when() returns.

Every statement verb lives here, spoken from a segment; ASPProgram's
verbs delegate to its default segment. fact() adds grounded atoms;
choose() adds a bare choice rule. when(*conditions) holds the
conditions and completes
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

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager

from pyclingo.choice import Choice
from pyclingo.conditioned_element import ConditionType
from pyclingo.core import Comparison, Pool, PredicateOccurrence, Term
from pyclingo.optimization import (
    Optimization,
    OptimizationDirective,
    OptimizationTermType,
    WeakConstraint,
)
from pyclingo.predicate import NegatedSignature, Predicate, PredicateClassType
from pyclingo.program_elements import BlankLine, Comment, ProgramElement, RawASP, RenderedLine, Rule
from pyclingo.scoping import validate_optimization_element, validate_weak_constraint
from pyclingo.source_location import SourceLocation, capture_location


def _build_weak_constraint(
    conditions: tuple[Term, ...],
    weight: int | OptimizationTermType,
    terms: Sequence[OptimizationTermType] | None,
    priority: int,
    check_singletons: bool,
) -> WeakConstraint:
    """The one assembly path both penalize() spellings share: build, validate, freeze."""
    weak = WeakConstraint(conditions, weight, tuple(terms) if terms is not None else None, priority)
    validate_weak_constraint(weak.targets, list(weak.conditions), weak.render(), check_singletons=check_singletons)
    weak.freeze()
    return weak


def _non_term_error(kind: str, got: object) -> TypeError:
    """The must-be-Terms rejection, teaching the predicate-equality trap on a bool."""
    if isinstance(got, bool):
        return TypeError(
            f"{kind} must be Terms, got bool: == between two predicate instances is "
            f"Python value equality (predicates are data). Bind one side to a Variable "
            f"and compare that (C == cell(1, 2)), or state the atoms separately."
        )
    return TypeError(f"{kind} must be Terms, got {type(got).__name__}")


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
    program's setting, and so does source_locations (whether appended
    elements are stamped with the user line that authored them).
    """

    def __init__(self, name: str, allow_singletons: bool = False, source_locations: bool = True) -> None:
        self._name = self.validate_name(name)
        self._elements: list[ProgramElement] = []
        self._check_singletons = not allow_singletons
        self._capture_locations = source_locations
        self._pending: list[When] = []

    @staticmethod
    def validate_name(name: str) -> str:
        """The name, exactly as given (as a plain str); rejects empty or multi-line ones."""
        if not isinstance(name, str):
            raise TypeError(f"Segment name must be a string, got {type(name).__name__}")
        # A subclass converts to its natural plain str first, so the checks
        # below see exactly the name that will render
        name = str(name)
        if not name.strip():
            raise ValueError("Segment names cannot be empty")
        if "\n" in name or "\r" in name:
            raise ValueError("Segment names must be single-line (they render as section comments)")
        if "\x00" in name:
            raise ValueError(
                "Segment names cannot contain NUL: clingo silently truncates the program at the first NUL byte"
            )
        return name

    @property
    def name(self) -> str:
        """The segment's name."""
        return self._name

    def _append(self, element: ProgramElement) -> None:
        """
        Add an element to the end of the segment. Every statement verb ends
        here, so this is also where the element is stamped with the user
        line that authored it (unless the When machinery already did).
        Formatting elements (_locatable=False) are never stamped.

        Private: elements are internal records — the statement verbs are
        the writing surface, raw_asp() the escape hatch.
        """
        if not isinstance(element, ProgramElement):
            raise TypeError(
                f"_append() takes a ProgramElement, got {type(element).__name__}; for verbatim ASP text use raw_asp()"
            )
        if self._capture_locations and element._locatable and element.source_location is None:
            element._source_location = capture_location()
        self._elements.append(element)

    def __len__(self) -> int:
        """The number of statements recorded in this segment."""
        return len(self._elements)

    def __iter__(self) -> Iterator[ProgramElement]:
        """
        Iterate the segment's statements as OPAQUE ProgramElements: read
        render() and source_location off them. The concrete classes are
        internal — the statement verbs are the writing surface.
        """
        return iter(self._elements)

    # ---- statement verbs ----

    def fact(self, *facts: Predicate) -> None:
        """Add unconditional statements: grounded atoms, asserted true."""
        if not facts:
            raise ValueError("fact() requires at least one statement")
        for statement in facts:
            if isinstance(statement, Choice):
                raise TypeError(
                    f"A choice rule ({statement.render()}) is not a fact — nothing is "
                    f"asserted, the solver picks. State it with choose() instead."
                )
            if not isinstance(statement, Predicate):
                raise TypeError(f"fact() arguments must be Predicate instances, got {type(statement).__name__}")
            if not statement.is_grounded:
                variables = ", ".join(sorted(statement.collect_variables()))
                raise ValueError(
                    f"fact() requires grounded predicates, but {statement.render()} contains "
                    f"variable(s) {variables}. Use when(*conditions).derive(...) to derive predicates."
                )
        for statement in facts:
            rule = Rule(head=statement, check_singletons=self._check_singletons)
            self._append(rule)

    def choose(self, choice: Choice) -> None:
        """
        Add a bare choice rule: "{ elements } bounds." with no body — the
        solver freely picks which elements hold, within the bounds.
        Element variables are local to their conditions. A choice under
        conditions is spelled when(*conditions).derive(choice).
        """
        if isinstance(choice, Predicate):
            raise TypeError(
                f"choose() takes a Choice, got the atom {choice.render()} — "
                f"an atom asserted unconditionally is a fact: fact({choice.render()})"
            )
        if not isinstance(choice, Choice):
            raise TypeError(f"choose() takes a Choice, got {type(choice).__name__}")
        rule = Rule(head=choice, check_singletons=self._check_singletons)
        self._append(rule)

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
                raise _non_term_error("when() conditions", condition)
        return When(self, conditions)

    def forbid(self, *conditions: Term) -> None:
        """Forbid the combination: no answer set may satisfy all conditions."""
        if not conditions:
            raise ValueError("forbid() requires at least one condition")
        for condition in conditions:
            if not isinstance(condition, Term):
                raise _non_term_error("forbid() conditions", condition)
        rule = Rule(body=list(conditions), check_singletons=self._check_singletons)
        self._append(rule)

    def require(self, comparison: Comparison) -> None:
        """
        Require that a comparison holds in every answer set. Takes exactly
        one Comparison; a conditional requirement is spelled
        when(*conditions).require(comparison). Sugar for forbidding the
        inverse comparison.
        """
        target = _required_comparison(comparison)
        rule = Rule(body=[target.inverse()], check_singletons=self._check_singletons)
        self._append(rule)

    def penalize(
        self,
        *conditions: Term,
        weight: int | OptimizationTermType = 1,
        terms: Sequence[OptimizationTermType] | None = None,
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

        Tuple identity follows the spelling. By default the library owns
        it: the tuple gets the conditions' variables plus a per-statement
        "weak-constraint-N" tag, so each ground match of THIS statement is
        charged once — two penalties over one domain never merge charges.
        Pass terms= to own the identity yourself (rendered exactly as
        given, shared tuple-set semantics included) — terms=[] deliberately
        collapses EVERY match into one charge (gringo's own bare-tuple
        semantics). Every weight/terms variable must be bound by the
        conditions. A negative literal weight is rejected — that is a
        reward, not a penalty; spell it minimize()/maximize().
        """
        weak = _build_weak_constraint(conditions, weight, terms, priority, self._check_singletons)
        self._append(weak)

    def minimize(
        self,
        weight: int | OptimizationTermType,
        *terms: OptimizationTermType,
        condition: ConditionType | list[ConditionType] | None = None,
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
        self._add_optimization(Optimization.MINIMIZE, weight, terms, condition, priority)

    def maximize(
        self,
        weight: int | OptimizationTermType,
        *terms: OptimizationTermType,
        condition: ConditionType | list[ConditionType] | None = None,
        priority: int = 0,
    ) -> None:
        """
        Add a #maximize statement: prefer answer sets with the LARGEST
        total weight. Exactly minimize() with the preference flipped
        (clingo reports the cost of a maximization as a negated sum). See
        minimize() for the tuple-distinctness and priority rules.
        """
        self._add_optimization(Optimization.MAXIMIZE, weight, terms, condition, priority)

    def _add_optimization(
        self,
        sense: Optimization,
        weight: int | OptimizationTermType,
        terms: tuple[OptimizationTermType, ...],
        condition: ConditionType | list[ConditionType] | None,
        priority: int,
    ) -> None:
        directive = OptimizationDirective(sense, weight, terms, condition, priority)
        validate_optimization_element(directive.element, directive.render(), check_singletons=self._check_singletons)
        directive.element.freeze()
        self._append(directive)

    def raw_asp(self, text: str, predicates: Sequence[PredicateClassType | NegatedSignature] = ()) -> None:
        """
        Add a verbatim block of ASP text: the escape hatch for constructs
        pyclingo does not model.

        Declare any predicates the block produces via predicates so that show
        directives cover them and solutions round-trip into typed instances
        (atoms carrying escaped strings are the exception — pyclingo has no
        escaping support; hide() such classes).
        Declaring the class P covers round-trip and the collision check for
        both signs, and emits "#show p/n."; if the block also derives
        classically negated atoms, declare -P as well to emit "#show -p/n."
        (predicates=[P, -P]), or the -p atoms stay absent from output.

        A #script block must open and close within ONE raw block: splitting
        it across blocks (or segments) defeats the per-segment scan that
        keeps render(annotate=True) notes out of embedded source, and the
        second block's text is judged as ASP rather than script.

        Directives that need solver configuration ground SILENTLY INERT
        under the pyclingo verbs: #project does nothing until the solve
        projects (grounded.control.configuration.solve.project =
        "project"), and #heuristic does nothing until the Domain heuristic
        is on (grounded.control.configuration.solver.heuristic = "Domain").
        Set the knob through the control escape hatch between ground() and
        the solve, or the directive quietly changes nothing.
        """
        if not isinstance(text, str):
            raise TypeError(f"raw_asp() text must be a string, got {type(text).__name__}")
        self._append(RawASP(text, predicates))

    def comment(self, text: str) -> None:
        """Add a comment."""
        self._append(Comment(text))

    def blank_line(self) -> None:
        """Add a blank line for formatting."""
        self._append(BlankLine())

    def section(self, title: str) -> None:
        """Add a blank line and title comment as a section header."""
        self.blank_line()
        self.comment(title)

    # ---- rendering and walking ----

    def render(self, with_header: bool = False) -> str:
        """
        Render the segment's elements, one per line. With with_header, the
        elements are framed by a blank line, a "% ===== name =====" section
        comment, and one blank line — any blank the content already opens
        with is absorbed, so the gap after the header is always exactly one.
        Raises if any when() in this segment was never completed.

        This is a FRAGMENT: weak constraints render with bare tuples here,
        where the program-level render adds weak-constraint discriminators.
        """
        return "\n".join(line.text for line in self.render_lines(with_header))

    def render_lines(
        self, with_header: bool, weak_discriminators: Mapping[int, int] | None = None
    ) -> list[RenderedLine]:
        """
        The segment's rendered lines, each carrying the element that
        produced it (framing lines carry None) — a multi-line element
        claims every one of its lines. render() joins the text column; the
        program builds its line-provenance map from the element column.
        weak_discriminators (id(element) -> ordinal) is the program
        render's per-statement tags for auto-tupled weak constraints;
        standalone renders pass none and render bare tuples. Raises if any
        when() in this segment was never completed.
        """
        self.check_pending()
        lines: list[RenderedLine] = []
        for element in self._elements:
            if isinstance(element, WeakConstraint) and weak_discriminators is not None:
                rendered = element.render(discriminator=weak_discriminators.get(id(element)))
            else:
                rendered = element.render()
            # split("\n"), not splitlines(): a trailing newline in raw text
            # must keep contributing its empty line, exactly as when whole
            # rendered elements were joined
            lines.extend(RenderedLine(text, element) for text in rendered.split("\n"))
        if with_header:
            while lines and lines[0].text == "":
                lines.pop(0)
            lines = [
                RenderedLine("", None),
                RenderedLine(f"% ===== {self._name} =====", None),
                RenderedLine("", None),
                *lines,
            ]
        return lines

    def check_pending(self) -> None:
        """Raise if any when() on this segment is still awaiting its closer."""
        if self._pending:
            listing = "; ".join(
                f"when({', '.join(c.render() for c in w.conditions)})"
                + (f" opened at {w.location.display()}" if w.location is not None else "")
                for w in self._pending
            )
            raise ValueError(
                f"Segment '{self._name}' has incomplete when() statements: {listing}. "
                f"Complete each with .derive/.require/.forbid/.penalize."
            )

    def collect_predicate_occurrences(self) -> set[PredicateOccurrence]:
        """(class, negated, is_atom) across the segment's elements, which are top-level statements (atom position)."""
        occurrences: set[PredicateOccurrence] = set()
        for element in self._elements:
            occurrences.update(element.collect_predicate_occurrences(as_argument=False))
        return occurrences

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
    left incomplete (no closer ever ran) fails the render.

    A closer that RAISES unregisters the When instead: its error already
    reported the problem loudly at the author's line, so the fluent
    spelling (when(...).derive(bad)), which holds no reference, does not
    leave a poisoned pending entry behind. A held reference may still
    complete it with a corrected closer.
    """

    def __init__(self, segment: Segment, conditions: tuple[Term, ...]) -> None:
        self._segment = segment
        self._conditions = conditions
        self._completed_by: str | None = None
        # Captured here, not at the closer: a dangling When's whole
        # diagnosis is where it was opened, and by definition no closer ran
        self._location = capture_location() if segment._capture_locations else None
        segment._pending.append(self)

    @property
    def conditions(self) -> tuple[Term, ...]:
        """The held conditions."""
        return self._conditions

    @property
    def location(self) -> SourceLocation | None:
        """The user line that opened this when(), if capture is on."""
        return self._location

    def _complete(self, closer: str, element: ProgramElement) -> None:
        # The element is fully built (and validated) before the context
        # resolves, so a rejected statement leaves the When retryable.
        # Every closer runs _guard() BEFORE building its element (a second
        # closer must fail before Rule() freezes shared builders), so no
        # completed When can reach here.
        self._completed_by = closer
        if self in self._segment._pending:
            self._segment._pending.remove(self)
        # The element anchors at the when() line; a closer on a different
        # line is recorded too — a fluent chain's halves can sit far apart
        if self._location is not None:
            element._source_location = self._location
            closed = capture_location()
            if closed is not None and closed != self._location:
                element._closed_at = closed
        self._segment._append(element)

    def _guard(self) -> None:
        if self._completed_by is not None:
            raise RuntimeError(
                f"This when() was already completed with .{self._completed_by}(); "
                f"it takes exactly one statement — call when() again for another"
            )

    @contextmanager
    def _unregister_on_error(self) -> Iterator[None]:
        # A raising closer already reported its problem loudly; keeping the
        # When pending would poison every future render for the fluent
        # caller, who holds no reference to complete or discard it
        try:
            yield
        except BaseException:
            if self in self._segment._pending:
                self._segment._pending.remove(self)
            raise

    def derive(self, head: Term) -> None:
        """
        Add head with the conditions as its body: "head :- conditions.". The
        head is any rule head — an atom or a Choice.
        """
        with self._unregister_on_error():
            if not isinstance(head, Term):
                raise TypeError(f"derive() head must be a Term, got {type(head).__name__}")
            self._guard()
            rule = Rule(head=head, body=list(self._conditions), check_singletons=self._segment._check_singletons)
            self._complete("derive", rule)

    def require(self, comparison: Comparison) -> None:
        """
        Require the comparison to hold under the conditions. Takes exactly
        one Comparison; sugar for forbid(*conditions, comparison.inverse()).
        """
        with self._unregister_on_error():
            target = _required_comparison(comparison)
            self._guard()
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
        with self._unregister_on_error():
            if not violation:
                raise ValueError(
                    "when(...).forbid() takes at least one violation term; to forbid the "
                    "conditions themselves, use the flat forbid(*conditions)"
                )
            for term in violation:
                if not isinstance(term, Term):
                    raise _non_term_error("forbid() violation terms", term)
            self._guard()
            rule = Rule(
                body=[*self._conditions, *violation],
                check_singletons=self._segment._check_singletons,
            )
            self._complete("forbid", rule)

    def penalize(
        self,
        *violation: Term,
        weight: int | OptimizationTermType = 1,
        terms: Sequence[OptimizationTermType] | None = None,
        priority: int = 0,
    ) -> None:
        """
        Charge for the conditions together with the violation instead of
        forbidding them: a weak constraint over the same body forbid() would
        reject. Takes at least one violation term; weight/terms/priority as
        in the flat penalize().
        """
        with self._unregister_on_error():
            if not violation:
                raise ValueError(
                    "when(...).penalize() takes at least one violation term; to charge for the "
                    "conditions themselves, use the flat penalize(*conditions)"
                )
            for term in violation:
                if not isinstance(term, Term):
                    raise _non_term_error("penalize() violation terms", term)
            self._guard()
            weak = _build_weak_constraint(
                (*self._conditions, *violation), weight, terms, priority, self._segment._check_singletons
            )
            self._complete("penalize", weak)


def _required_comparison(target: Comparison) -> Comparison:
    """The require() operand, with teaching errors for the wrong-type and pool shapes."""
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
