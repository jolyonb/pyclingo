"""
Tests for the ground()/solve() split: ground once, solve many times, with
the sequential-solve and staleness contracts enforced loudly.
"""

import inspect
import threading
import time
from itertools import islice
from typing import Any

import clingo
import pytest

from aspalchemy import (
    ASPProgram,
    Choice,
    Count,
    Number,
    Predicate,
    RangePool,
    SignatureGrounding,
    SourceLocation,
    UnsatisfiableError,
    Variable,
)
from aspalchemy.solver import GroundedProgram

A = Predicate.define("a", ["value"])


def make_program(n: int = 3) -> ASPProgram:
    """2^n models: an unconstrained choice over a(1..n)."""
    program = ASPProgram()
    program.choose(Choice(A(value=RangePool(1, n))))
    return program


def test_ground_once_solve_repeatedly() -> None:
    grounded = make_program().ground()
    first = grounded.solve()
    assert len(list(first)) == 8
    second = grounded.solve()
    assert len(list(second)) == 8
    assert first.exhausted and second.exhausted


def test_per_solve_consumption_on_one_grounding() -> None:
    grounded = make_program().ground()
    assert len(list(grounded.solve())) == 8
    partial = grounded.solve()
    assert len(list(islice(partial, 2))) == 2
    partial.close()  # early-stopped: free the grounding for the next solve
    assert len(list(grounded.solve())) == 8


def test_overlapping_solves_rejected() -> None:
    grounded = make_program().ground()
    first = grounded.solve()
    next(iter(first))  # started but unconsumed
    with pytest.raises(RuntimeError, match="still open"):
        grounded.solve()
    first.close()
    assert grounded.solve() is not None  # closed counts as finished


def test_grounding_is_an_independent_snapshot() -> None:
    # Like a compiled regex: the handle holds the text it was made from,
    # unaffected by later mutation of the program
    program = make_program()
    P = Predicate.define("p_extra", ["x"], show=False)
    Q = Predicate.define("q_extra", ["x"])
    before = program.ground()
    program.fact(P(x=1))
    program.when(P(x=1)).derive(Q(x=1))
    after = program.ground()
    assert "p_extra" not in before.text
    assert "p_extra" in after.text
    # Both handles solve their own program — side-by-side comparison works
    model_before = next(iter(before.solve()))
    model_after = next(iter(after.solve()))
    assert model_before.atoms(Q) == []
    assert len(model_after.atoms(Q)) == 1


def test_one_shot_solve_unchanged() -> None:
    # solve() is sugar for ground().solve(); behavior identical
    result = make_program().solve()
    assert len(list(result)) == 8
    assert result.statistics is not None
    assert "wall_time" in result.statistics


def test_messages_window_per_solve_on_shared_handler() -> None:
    # The handler is shared across a grounding's solves; each solve clears
    # the list at start (the sequential guard proves nobody is mid-window),
    # and each result sees only messages arriving within its own window.
    # Injection stands in for solve-phase messages.
    grounded = make_program().ground()

    first = grounded.solve()
    iterator = iter(first)
    next(iterator)
    handler = grounded._message_handler
    handler.on_message(clingo.MessageCode.Other, "info: during first solve")
    list(iterator)
    assert len(first.messages) == 1

    second = grounded.solve()
    list(second)
    assert second.messages == ()  # the first solve's message was cleared
    assert grounded._message_handler.messages == []  # nothing accumulates across solves


def test_abandon_frees_the_grounding() -> None:
    grounded = make_program().ground()
    first = grounded.solve()
    next(iter(first))  # open and unconsumed
    grounded.abandon()
    assert first.finished
    assert len(list(grounded.solve())) == 8


def test_abandon_is_idempotent_and_safe_when_nothing_is_open() -> None:
    grounded = make_program().ground()
    grounded.abandon()  # nothing open: no-op
    result = grounded.solve()
    list(result)
    grounded.abandon()  # already finished: no-op
    grounded.abandon()
    assert len(list(islice(grounded.solve(), 2))) == 2


def test_assumptions_filter_models_per_solve() -> None:
    grounded = make_program().ground()  # {a(1..3)}: 8 models
    assert len(list(grounded.solve(assumptions=[A(value=1)]))) == 4
    assert len(list(grounded.solve(assumptions=[~A(value=1)]))) == 4
    assert len(list(grounded.solve(assumptions=[A(value=1), ~A(value=2)]))) == 2
    # Assumptions never persist: the next solve is unconstrained
    assert len(list(grounded.solve())) == 8


def test_assumed_atoms_appear_in_every_model() -> None:
    grounded = make_program().ground()
    for model in grounded.solve(assumptions=[A(value=2)]):
        assert A(value=2) in set(model.atoms(A))


def test_assuming_a_fact_false_is_unsat() -> None:
    program = ASPProgram()
    F = Predicate.define("f_assume", ["x"])
    program.fact(F(x=9))
    grounded = program.ground()
    result = grounded.solve(assumptions=[~F(x=9)])
    assert list(result) == []
    assert result.satisfiable is False


def test_absent_atom_assumption_raises_with_teaching() -> None:
    grounded = make_program().ground()
    Ghost = Predicate.define("ghost", ["x"])
    with pytest.raises(ValueError, match="does not occur in this grounding"):
        grounded.solve(assumptions=[Ghost(x=7)])
    with pytest.raises(ValueError, match="does not occur in this grounding"):
        grounded.solve(assumptions=[~Ghost(x=7)])


def test_ungrounded_and_wrong_type_assumptions_rejected() -> None:
    grounded = make_program().ground()
    X = Variable("X")
    with pytest.raises(ValueError, match="must be grounded"):
        grounded.solve(assumptions=[A(value=X)])
    with pytest.raises(TypeError, match="predicate atoms"):
        grounded.solve(assumptions=[X == 1])  # type: ignore[list-item]


def test_assumptions_resolve_defined_constants() -> None:
    # gringo substitutes #const at grounding, so the ground atom carries the
    # value; the handle resolves the reference through its snapshot
    program = ASPProgram()
    F = Predicate.define("f_const", ["x"])
    n = program.define_constant("n_assume", 4)
    program.choose(Choice(F(x=RangePool(1, n))))
    grounded = program.ground()
    result = grounded.solve(assumptions=[F(x=n)])
    models = list(result)
    assert all(F(x=4) in set(m.atoms(F)) for m in models)
    assert len(models) == 8  # 2^3 for the other slots


def test_assumptions_resolve_atom_valued_constants() -> None:
    # An atom-valued #const resolves through the same snapshot, recursively:
    # the assumption f(dir) reaches clasp as f(n)
    program = ASPProgram()
    N = Predicate.define("n_av", [], show=False)
    F = Predicate.define("f_av", ["x"])
    dir_const = program.define_constant("dir_av", N())
    picks = Choice(F(x=N()))
    picks.add(F(x=1))
    program.choose(picks)
    grounded = program.ground()
    models = list(grounded.solve(assumptions=[F(x=dir_const)]))
    assert all(F(x=N()) in set(m.atoms(F)) for m in models)
    assert len(models) == 2  # the other slot stays free


def test_assumptions_resolve_string_valued_constants() -> None:
    # The third value shape: a string const resolves to the quoted string
    program = ASPProgram()
    F = Predicate.define("f_sv", ["x"])
    s = program.define_constant("s_av", "hello")
    program.choose(Choice(F(x=s)))
    grounded = program.ground()
    models = list(grounded.solve(assumptions=[F(x=s)]))
    assert len(models) == 1
    assert models[0].atoms(F) == [F(x="hello")]


def test_expression_assumptions_rejected_with_teaching() -> None:
    grounded = make_program().ground()
    with pytest.raises(ValueError, match="pass the computed value"):
        grounded.solve(assumptions=[A(value=Number(1) + 1)])


def test_assumption_rejection_names_the_inner_term() -> None:
    grounded = make_program().ground()
    X = Variable("X")
    # ~(plain comparison) IS the complementary comparison, so the rejection
    # names it bare...
    with pytest.raises(TypeError, match="got Comparison"):
        grounded.solve(assumptions=[~(X == 3)])  # type: ignore[list-item]
    # ...while a genuinely wrapped negation (aggregate comparisons keep the
    # wrapper) is named through its ~
    with pytest.raises(TypeError, match="got ~Comparison"):
        grounded.solve(assumptions=[~(Count(X, condition=A(value=X)) > 1)])  # type: ignore[list-item]


def test_project_shown_collapses_helper_variants() -> None:
    # Two aux arrangements per solution: raw enumeration counts 4, projected
    # counts 2 — the islice-2 uniqueness check becomes honest
    def build() -> ASPProgram:
        program = ASPProgram()
        Sol = Predicate.define("sol", [])
        Aux = Predicate.define("aux", [], show=False)
        program.choose(Choice(Sol()))
        program.choose(Choice(Aux()))
        return program

    raw = build()
    assert len(list(raw.solve())) == 4

    projected = build()
    projected.project_shown = True
    result = projected.solve()
    assert len(list(result)) == 2
    assert "--project=show" in projected.render()  # the artifact says so


def test_project_shown_off_by_default() -> None:
    program = ASPProgram()
    assert program.project_shown is False
    assert "--project=show" not in program.render()  # no stamp when off
    P = Predicate.define("p_projd", ["x"])
    program.fact(P(x=1))
    assert "project" not in program.render()


def test_racing_solves_admit_exactly_one() -> None:
    # The sequential guard is locked: of two threads racing solve() on one
    # grounding, exactly one wins and the other hits the teaching error —
    # never two searches silently sharing one Control (the unlocked
    # check-then-set admitted both in 93/500 trials — at that 18.6% rate,
    # 100 trials miss a regression with odds below 1e-8; each is ~ms)
    program = ASPProgram()
    P = Predicate.define("p_race_seq", ["x"])
    program.choose(Choice(P(x=RangePool(1, 3))))
    for _ in range(100):
        grounded = program.ground()
        outcomes: list[str] = []
        barrier = threading.Barrier(2)

        def attempt(
            grounded: GroundedProgram = grounded,
            outcomes: list[str] = outcomes,
            barrier: threading.Barrier = barrier,
        ) -> None:
            barrier.wait()
            try:
                grounded.solve()
                outcomes.append("admitted")
            except RuntimeError:
                outcomes.append("refused")

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == ["admitted", "refused"]
        grounded.abandon()


def test_control_escape_hatch_exposes_clingo_internals() -> None:
    # Use-at-your-own-risk access to the underlying Control: aspalchemy's
    # guarantees stop at this property, but the internals are reachable —
    # here, the grounding's own atom table
    program = ASPProgram()
    P = Predicate.define("p_ctl", ["x"])
    program.fact(P(x=1), P(x=2))
    grounded = program.ground()
    assert isinstance(grounded.control, clingo.Control)
    assert len(list(grounded.control.symbolic_atoms)) == 2
    assert next(iter(grounded.solve())).atoms(P)  # the verbs still work alongside


def test_assumption_class_names_the_instance_spelling() -> None:
    # A class where an atom belongs used to name _PredicateMeta
    program = ASPProgram()
    P = Predicate.define("p_asmcls", ["x"])
    program.fact(P(x=1))
    with pytest.raises(TypeError, match=r"pass a grounded instance: p_asmcls\(\.\.\.\)"):
        program.ground().solve(assumptions=[P])  # type: ignore[list-item]


def test_sugar_verbs_take_assumptions() -> None:
    # The ASPProgram sugar verbs forward assumptions like every other
    # per-solve knob (previously the one missing parameter)
    program = ASPProgram()
    P = Predicate.define("p_sugar_asm", ["x"])
    program.choose(Choice(P(x=RangePool(1, 3))))
    models = list(program.solve(assumptions=[P(x=2)]))
    assert models and all(any(a["x"].value == 2 for a in m.atoms(P)) for m in models)
    cautious = program.cautious(assumptions=[P(x=2)])
    assert P(x=2) in cautious.atoms(P)
    brave = program.brave(assumptions=[~P(x=1)])
    assert P(x=1) not in brave.atoms(P)

    optimizing = ASPProgram()
    Q = Predicate.define("q_sugar_asm", ["x"])
    X = Variable("X")
    optimizing.choose(Choice(Q(x=RangePool(1, 3))).at_least(1))
    optimizing.minimize(X, condition=Q(x=X))
    best = optimizing.optimize(assumptions=[Q(x=3)])
    assert best.cost == (3,)  # q(3) forced in; the rest minimized away


class _Doubler:
    """A grounding context: @double(...) in raw text calls this method."""

    def double(self, x: clingo.Symbol) -> clingo.Symbol:
        return clingo.Number(x.number * 2)


def test_ground_context_backs_at_functions() -> None:
    # Raw-clingo territory passed through verbatim: the context object's
    # methods evaluate @-terms at grounding
    program = ASPProgram()
    Val = Predicate.define("val_ctx", ["x"])
    program.raw_asp("val_ctx(@double(21)).", predicates=[Val])
    model = program.ground(context=_Doubler()).solve().first()
    assert model.atoms(Val)[0]["x"] is Number(42)  # interned: identity is value


def test_analyze_grounding_ranks_signatures_and_names_the_lines() -> None:
    program = ASPProgram()
    P = Predicate.define("p_an", ["x"], show=False)
    Q = Predicate.define("q_an", ["x"], show=False)
    Pair = Predicate.define("pair_an", ["a", "b"])
    X, Y = Variable("X"), Variable("Y")
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    program.fact(*[P(x=i) for i in range(1, 4)])  # lineno + 1: 3 atoms, one shared line
    program.fact(*[Q(x=i) for i in range(1, 4)])  # lineno + 2
    program.when(P(x=X), Q(x=Y)).derive(Pair(a=X, b=Y))  # lineno + 3: the 9-atom product
    grounded = program.ground()
    report = grounded.analyze_grounding()
    lines = report.splitlines()
    assert lines[0] == "Grounding profile: 15 ground atoms across 3 signatures"
    pair_site = SourceLocation(frame.f_code.co_filename, lineno + 3).display()
    assert lines[1] == f"  pair_an/2: 9 atoms — derived at {pair_site}"
    fact_site = SourceLocation(frame.f_code.co_filename, lineno + 1).display()
    assert lines[2] == f"  p_an/1: 3 atoms — derived at {fact_site}"  # three facts, one deduped line
    # The prose renders grounding_profile(): the same rows, structured
    top = grounded.grounding_profile()[0]
    assert top == SignatureGrounding("pair_an", 2, 9, (SourceLocation(frame.f_code.co_filename, lineno + 3),))


def test_analyze_grounding_attributes_choices_and_raw_blocks() -> None:
    program = ASPProgram()
    Chosen = Predicate.define("chosen_an", ["x"])
    Raw = Predicate.define("raw_an", ["x"])
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    program.choose(Choice(Chosen(x=RangePool(1, 4))).exactly(2))  # lineno + 1
    program.raw_asp("raw_an(1..3).", predicates=[Raw])  # lineno + 2
    report = program.ground().analyze_grounding()
    choice_site = SourceLocation(frame.f_code.co_filename, lineno + 1).display()
    raw_site = SourceLocation(frame.f_code.co_filename, lineno + 2).display()
    assert f"  chosen_an/1: 4 atoms — derived at {choice_site}" in report
    assert f"  raw_an/1: 3 atoms — derived at {raw_site}" in report


def test_analyze_grounding_fallbacks_stay_honest() -> None:
    # Capture off: sites exist but carry no location. Declared-by-show raw
    # atoms: no deriving statement is known at all.
    program = ASPProgram(source_locations=False)
    P = Predicate.define("p_an_off", ["x"])
    Ghost = Predicate.define("ghost_an", ["x"])
    program.fact(P(x=1))
    program.raw_asp("ghost_an(1..2).")
    program.show(Ghost)  # show() declares as fully as predicates= — but derives nothing
    report = program.ground().analyze_grounding()
    assert "  p_an_off/1: 1 atoms — derived at unknown (source locations off)" in report
    assert "  ghost_an/1: 2 atoms — derived at no aspalchemy statement (declared but underived?)" in report


def test_comparison_head_rules_ground_and_analyze() -> None:
    # derive(X == Y) is a requirement on its body: it derives no atoms, and
    # grounding it must not trip analyze_grounding's head walk
    program = ASPProgram()
    P = Predicate.define("p_cmp", ["x"])
    Q = Predicate.define("q_cmp", ["x"])
    X, Y = Variable("X"), Variable("Y")
    program.fact(P(x=1), P(x=2), Q(x=2))
    program.when(P(x=X), Q(x=Y)).derive(X == Y)
    grounded = program.ground()  # the B-v regression died here with AssertionError
    assert list(grounded.solve()) == []  # p(1)/q(2) violates the required equality
    report = grounded.analyze_grounding()
    assert "p_cmp/1: 2 atoms" in report  # body signatures still reported; no head row


def test_executing_solve_refuses_abandon_close_and_next_and_teaches() -> None:
    # A solve blocked inside clasp on another thread cannot be injected
    # into: abandon(), close(), and a racing next() must all name their
    # remedies rather than leak generator internals — and abandon() must
    # still free the grounding once the search ends
    Pigeon = Predicate.define("pigeon_ab", ["p"], show=False)
    Assign = Predicate.define("assign_ab", ["p", "h"])
    program = ASPProgram()
    P, P2, H = Variable("P"), Variable("P2"), Variable("H")
    program.fact(*[Pigeon(p=i) for i in range(1, 15)])
    program.when(Pigeon(p=P)).derive(Choice(Assign(p=P, h=RangePool(1, 13))).exactly(1))
    program.forbid(Assign(p=P, h=H), Assign(p=P2, h=H), P < P2)  # 14/13: a long UNSAT proof
    grounded = program.ground()
    result = grounded.solve()
    iterator = iter(result)
    worker = threading.Thread(target=lambda: next(iterator, None))
    worker.start()
    try:
        # Poll until the worker is observably inside the generator (a fixed
        # sleep is a bet a starved CI runner loses); gi_running flips the
        # moment the frame is entered and stays up while clasp searches
        generator: Any = result._iterator._generator
        deadline = time.monotonic() + 10
        while not generator.gi_running and time.monotonic() < deadline:
            time.sleep(0.005)
        assert generator.gi_running, "worker never entered the search"
        with pytest.raises(RuntimeError, match=r"executing right now.*control\.interrupt"):
            grounded.abandon()
        with pytest.raises(RuntimeError, match=r"Only a suspended search can be stopped.*control\.interrupt"):
            result.close()
        with pytest.raises(RuntimeError, match=r"executing right now.*One consumer at a time"):
            next(iterator)
    finally:
        grounded.control.interrupt()
        worker.join(timeout=30)
    assert not worker.is_alive()
    grounded.abandon()  # the search is suspended now: freeing works quietly
    grounded.solve().close()  # and the grounding accepts the next solve


def test_unsat_core_names_the_conflicting_assumptions() -> None:
    program = ASPProgram()
    P = Predicate.define("p_core", ["x"])
    Q = Predicate.define("q_core", ["x"])
    program.choose(Choice(P(x=RangePool(1, 3))))
    program.fact(Q(x=1))
    program.forbid(P(x=1), P(x=2))  # p(1) and p(2) cannot coexist
    grounded = program.ground()
    result = grounded.solve(assumptions=[P(x=1), P(x=2), Q(x=1)])
    before = result.unsat_core
    assert before is None  # nothing proven yet
    assert list(result) == []
    core = result.unsat_core
    assert core is not None
    rendered = {atom.render() for atom in core}
    assert {"p_core(1)", "p_core(2)"} <= rendered  # the joint conflict is in the core
    assert result.satisfiable is False


def test_unsat_core_keeps_the_negated_shape() -> None:
    program = ASPProgram()
    Q = Predicate.define("q_core_neg", ["x"])
    program.fact(Q(x=1))
    grounded = program.ground()
    result = grounded.solve(assumptions=[~Q(x=1)])  # assume false what is a fact
    assert list(result) == []
    core = result.unsat_core
    assert core is not None and len(core) == 1
    assert core[0].render() == "not q_core_neg(1)"


def test_unsat_core_rides_the_eager_raise_and_the_iterator_handle() -> None:
    # Two routes to the core, one truth: the eager verb raises with it
    # attached, and the _iter twin's handle carries it after exhaustion
    # (the core-mapping terminal is shared by every mode)
    program = ASPProgram()
    P = Predicate.define("p_core_iter", ["x"])
    program.choose(Choice(P(x=RangePool(1, 3))))
    program.forbid(P(x=1), P(x=2))
    grounded = program.ground()
    with pytest.raises(UnsatisfiableError) as caught:
        grounded.cautious(assumptions=[P(x=1), P(x=2)])
    assert caught.value.unsat_core is not None
    assert {atom.render() for atom in caught.value.unsat_core} == {"p_core_iter(1)", "p_core_iter(2)"}
    steps = grounded.cautious_iter(assumptions=[P(x=1), P(x=2)])
    assert list(steps) == []  # zero approximations: UNSAT — streams never raise
    core = steps.unsat_core
    assert core is not None
    assert {atom.render() for atom in core} == {"p_core_iter(1)", "p_core_iter(2)"}


def test_unsat_core_is_empty_when_no_assumptions_conflict() -> None:
    # UNSAT with no assumptions: the core is empty, not None — the proof
    # needed nothing from the caller
    program = ASPProgram()
    P = Predicate.define("p_core_plain", ["x"])
    program.fact(P(x=1))
    program.forbid(P(x=1))
    result = program.solve()
    assert list(result) == []
    assert result.unsat_core == ()
    # And a satisfiable solve reports None: there is no core to speak of
    sat_program = ASPProgram()
    sat_program.fact(P(x=2))
    sat_result = sat_program.solve()
    assert len(list(sat_result)) == 1
    assert sat_result.unsat_core is None
