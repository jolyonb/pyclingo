"""
ASPProgram.copy() and Segment.copy(): independent copies.

The contract is "nothing mutable is shared". Both halves are load-bearing and
both are pinned here: writes to a copy must not reach the original (the point
of the method), while values, atoms and predicate CLASSES must come across as
the SAME objects (the library's identity contract — equal live values are one
object, and show settings are keyed by the classes the caller declared).

A GroundedProgram is the one thing a copy must NOT duplicate: it owns clingo's
Control, C state behind a cffi handle, and duplicating it segfaults the process
later. It hands itself back instead, which is also its meaning (an immutable
snapshot) — pinned below, because the failure it prevents is a hard crash with
no traceback.
"""

import copy
import subprocess
import sys
import textwrap

import pytest

from aspalchemy import ANY, ASPProgram, Choice, Comparison, Count, Field, Predicate, Segment, Variable
from aspalchemy.program_elements import Rule

N = Variable("N")


class Edge(Predicate, show=False):
    a: Field[str]
    b: Field[str]


class Node(Predicate):
    name: Field[str]


def build() -> ASPProgram:
    """A program with something of every kind in it."""
    program = ASPProgram()
    program.define_constant("n", 8)
    program.fact(Edge(a="x", b="y"))
    program.when(Edge(a=N, b=ANY)).derive(Node(name=N))
    program.add_segment("Extra").comment("a second segment")
    return program


def test_copy_renders_identically() -> None:
    program = build()
    assert program.copy().render() == program.render()


def test_writes_to_the_copy_do_not_reach_the_original() -> None:
    program = build()
    before = program.render()
    duplicate = program.copy()

    duplicate.fact(Edge(a="new", b="fact"))
    duplicate.define_constant("m", 3)
    duplicate.add_segment("Third")

    assert program.render() == before
    assert "new" in duplicate.render()
    assert "m = 3" in duplicate.render()
    assert "Third" in duplicate


def test_writes_to_the_original_do_not_reach_the_copy() -> None:
    program = build()
    duplicate = program.copy()
    before = duplicate.render()

    program.fact(Edge(a="later", b="fact"))

    assert duplicate.render() == before


def test_segments_and_their_element_lists_are_distinct_objects() -> None:
    program = build()
    duplicate = program.copy()

    for name in program:
        assert duplicate[name] is not program[name]
        assert len(duplicate[name]) == len(program[name])


def test_predicate_classes_survive_as_the_same_classes() -> None:
    """
    Show settings are keyed by class. A copied class would key nothing the
    caller can name, so the copy's shows would silently do nothing.
    """
    program = ASPProgram()
    program.fact(Edge(a="x", b="y"))
    program.when(Edge(a=N, b=ANY)).derive(Node(name=N))

    duplicate = program.copy()
    duplicate.hide(Node)

    assert "#show node/1." not in duplicate.render()
    assert "#show node/1." in program.render()


def test_a_solved_program_can_be_copied_and_pushed_further() -> None:
    """The motivating use: solve, then copy and make the copy unsatisfiable."""
    program = ASPProgram()
    program.fact(Edge(a="x", b="y"))
    program.when(Edge(a=N, b=ANY)).derive(Node(name=N))
    assert program.solve().first() is not None

    variant = program.copy()
    variant.forbid(Node(name=ANY))  # nothing may be a node — but x is

    assert not list(variant.solve())
    assert program.solve().first() is not None  # the original still solves


def test_copying_across_an_unfinished_when_is_refused() -> None:
    """
    A When holds the segment it will write to, so a copy taken while one is
    open has no honest answer: the handle the caller holds belongs to the
    original, and a copied When would be reachable through nothing public.
    Refuse at the copy, not later at a render that blames a closed when().
    """
    program = ASPProgram()
    pending = program.when(Edge(a=N, b=ANY))  # opened, not yet closed

    with pytest.raises(ValueError, match=r"Cannot copy segment 'Rules'.*when\(\) is unfinished"):
        program.copy()
    with pytest.raises(ValueError, match=r"Cannot copy segment 'Rules'"):
        program["Rules"].copy()

    # Closing it makes the program copyable, and the copy carries the rule
    pending.derive(Node(name=N))
    assert len(program.copy()["Rules"]) == 1


def test_a_segment_handle_keeps_writing_to_the_original() -> None:
    """
    add_segment() promises that appends through the handle you gave it are
    visible. After a copy, that handle still means the ORIGINAL — the copy has
    its own segment of that name, reached through the copy.
    """
    program = ASPProgram()
    handle = program.add_segment("Extra")

    duplicate = program.copy()
    handle.fact(Edge(a="x", b="y"))

    assert duplicate["Extra"] is not handle
    assert len(program["Extra"]) == 1
    assert len(duplicate["Extra"]) == 0


def test_flags_are_carried_across() -> None:
    program = ASPProgram(allow_singletons=True, source_locations=False)
    duplicate = program.copy()

    assert duplicate._check_singletons is program._check_singletons
    assert duplicate._source_locations is program._source_locations
    # and they still reach the segments the copy creates
    duplicate.fact(Edge(a="x", b="y"))
    assert duplicate["Rules"]._capture_locations is False


def test_segment_copy_is_independent() -> None:
    segment = Segment("Rules")
    segment.fact(Edge(a="x", b="y"))

    duplicate = segment.copy()
    duplicate.fact(Edge(a="new", b="fact"))

    assert len(segment) == 1
    assert len(duplicate) == 2


def test_segment_copy_can_be_renamed_and_re_attached() -> None:
    """A copy destined for the same program needs a new name: name is the key."""
    program = ASPProgram()
    program.fact(Edge(a="x", b="y"))

    program.add_segment(program["Rules"].copy(name="Mirror"))

    assert program["Mirror"].name == "Mirror"
    assert program.render().count('edge("x", "y").') == 2


def test_segment_copy_rejects_an_invalid_name() -> None:
    with pytest.raises(ValueError, match="NUL"):
        Segment("Rules").copy(name="bad\x00name")


def test_a_grounding_hands_itself_back_instead_of_duplicating() -> None:
    """
    Duplicating a GroundedProgram would duplicate clingo's Control — one C
    object owned by two Python objects, which crashes later and elsewhere. It
    is an immutable snapshot, so sharing is both the safe answer and the true
    one.
    """
    program = ASPProgram()
    program.fact(Edge(a="x", b="y"))
    grounded = program.ground()

    assert copy.copy(grounded) is grounded
    assert copy.deepcopy(grounded) is grounded
    # and the shared handle is still a working grounding, not a husk
    assert len(list(grounded.solve())) == 1


def test_copying_a_program_that_holds_a_grounding_is_safe() -> None:
    """
    The path that reached users: a subclass caching its own grounding. Before
    the __deepcopy__ hook this raised (cannot pickle a cffi handle) — and a
    duplicated Control would have segfaulted at teardown.
    """

    class Cached(ASPProgram):
        def __init__(self) -> None:
            super().__init__()
            self._grounded: object | None = None

        def memoize(self) -> None:
            self._grounded = self.ground()

    program = Cached()
    program.fact(Edge(a="x", b="y"))
    program.memoize()

    duplicate = program.copy()

    assert duplicate._grounded is program._grounded  # shared snapshot, not a clone
    assert duplicate.render() == program.render()


def test_an_abandoned_search_does_not_crash_the_interpreter() -> None:
    """
    Regression, and it can only be seen from outside: a search that is never
    exhausted and never closed is finalized by the GC during interpreter
    shutdown, when clingo's module state may already be gone. Reading native
    statistics off the Control there dereferenced freed memory — SIGSEGV, no
    traceback, ~2 runs in 3. The generator now skips the snapshot while the
    interpreter is finalizing, so this exits cleanly every time.
    """
    script = textwrap.dedent("""
        from aspalchemy import ASPProgram, Field, Predicate

        class Seed(Predicate):
            x: Field[int]

        program = ASPProgram()
        program.fact(Seed(x=1), Seed(x=2))
        result = program.ground().solve()
        next(iter(result))     # one model, then walk away
    """)
    for _ in range(5):
        completed = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=60)
        assert completed.returncode == 0, (
            f"abandoned search crashed the interpreter: exit {completed.returncode} "
            f"(negative or >=128 means a signal; SIGSEGV is the regression)"
        )


def test_a_user_cycle_capturing_an_abandoned_search_does_not_crash() -> None:
    """
    Regression, the mid-run sibling of the shutdown crash above: a caller's
    reference cycle that captures a grounding with a suspended search makes
    grounding, handle, generator, and Control garbage TOGETHER, and cycle
    collection runs their finalizers in undefined order — Control.__del__
    could free the native object before GeneratorExit reached the generator,
    whose cleanup then called native clingo on freed memory. SIGSEGV, no
    traceback, deterministic. Every native teardown call is now guarded by
    _control_finalized() (gc.is_finalized answers the ordering question
    exactly), so this exits cleanly.
    """
    script = textwrap.dedent("""
        import gc

        from aspalchemy import ASPProgram, Field, Predicate

        class Seed(Predicate):
            x: Field[int]

        def one_round():
            program = ASPProgram()
            program.fact(Seed(x=1), Seed(x=2))
            grounding = program.ground()
            next(iter(grounding.solve()))    # suspend the search, then abandon it
            holder = {}
            holder["self"] = holder          # the user cycle...
            holder["grounding"] = grounding  # ...capturing the whole cluster

        for _ in range(25):
            one_round()
            gc.collect()
    """)
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=60)
    assert completed.returncode == 0, (
        f"cycle-captured abandoned search crashed the interpreter: exit {completed.returncode} "
        f"(negative or >=128 means a signal; SIGSEGV is the regression)"
    )


# --- builders: Choice and Aggregate -----------------------------------------
#
# A builder is the one mutable thing a rule can record, so its copy semantics
# are load-bearing in a way the program's are not: copy() must hand back
# something a rule does NOT hold (so it may be built on), while copy.copy and
# copy.deepcopy must be faithful (so a copied program's recorded rules stay
# fenced). The two must not be conflated.


def test_add_returns_none_on_both_builders() -> None:
    """
    The contract of 1.3.0: a builder's mutator returns None. Pinned at runtime
    because the annotation and the behaviour could drift back together — revert
    both and every call site still works.

    The ignores are the point, not a wart: mypy REFUSES to let this be written
    without them ("add of Choice does not return a value"), which is the same
    contract, enforced statically.
    """
    X = Variable("X")
    P = Predicate.define("p_ar", ["x"])

    menu = Choice(P(x=X))
    assert menu.add(P(x=1)) is None  # type: ignore[func-returns-value]

    tally = Count(X, condition=P(x=X))
    assert tally.add(1, P(x=1)) is None  # type: ignore[func-returns-value]


def test_aggregate_copy_is_mutable_and_its_hooks_are_faithful() -> None:
    """Same three-way split as Choice — pinned for the second builder too."""
    program = ASPProgram()
    X = Variable("X")
    P, Q = (Predicate.define(name, ["x"]) for name in ("p_ag", "q_ag"))

    tally = Count(X, condition=P(x=X))
    program.forbid(tally > 1)  # captured: frozen

    fresh = tally.copy()  # copy(): mutable
    fresh.add(X, Q(x=X))
    assert fresh.render() == "#count{ X : p_ag(X); X : q_ag(X) }"
    assert tally.render() == "#count{ X : p_ag(X) }"

    for duplicate in (copy.copy(tally), copy.deepcopy(tally)):  # hooks: faithful
        assert duplicate._frozen is True
        with pytest.raises(RuntimeError, match="frozen"):
            duplicate.add(X, Q(x=X))
        assert duplicate._elements is not tally._elements


def test_copy_carries_the_bounds_across() -> None:
    P = Predicate.define("p_bc", ["x"])
    bounded = Choice(P(x=1)).exactly(2)
    assert bounded.copy().render() == "{ p_bc(1) } = 2"


def test_an_aggregate_in_a_rule_body_stays_frozen_across_a_program_copy() -> None:
    """
    The head case is pinned above; the BODY case travels a different path
    through the rule, and is the one a program copy is most likely to reach.
    """
    program = ASPProgram()
    X = Variable("X")
    P = Predicate.define("p_ab", ["x"])

    tally = Count(X, condition=P(x=X))
    program.forbid(tally > 1)

    duplicate = program.copy()
    body_rule = next(iter(duplicate["Rules"]))
    assert isinstance(body_rule, Rule)
    held = next(term for term in body_rule.body if isinstance(term, Comparison))
    aggregate = held.left_term
    assert isinstance(aggregate, Count)
    assert aggregate._captured_at == tally._captured_at  # the receipt travels
    with pytest.raises(RuntimeError, match="frozen"):
        aggregate.add(X, P(x=1))


def test_copy_of_a_frozen_bounded_choice_carries_its_bounds() -> None:
    program = ASPProgram()
    P = Predicate.define("p_fb", ["x"])
    bounded = Choice(P(x=1)).exactly(2)
    program.choose(bounded)  # frozen, and bounded

    fresh = bounded.copy()
    fresh.add(P(x=2))  # mutable
    assert fresh.render() == "{ p_fb(1); p_fb(2) } = 2"  # bounds came across
