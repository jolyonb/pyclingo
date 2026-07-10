"""
Tests for cautious/brave consequences: probe-mirrored. clasp computes them
by refinement — successive approximations where only the last is the
answer — so these tests pin that the final answer is the true
intersection/union, the path keeps every approximation (the receipts),
and interrupted refinements return honestly one-sided partial results.
"""

import pytest

from pyclingo import (
    ANY,
    ASPProgram,
    AtomCollection,
    BraveConsequences,
    CautiousConsequences,
    Choice,
    Consequences,
    Count,
    Predicate,
    RangePool,
    Variable,
)

Color = Predicate.define("color", ["x"])
Dom = Predicate.define("dom", ["x"], show=False)
Forced = Predicate.define("forced", [])


def build() -> ASPProgram:
    # Answer sets: {c3}, {c1}, {c1,c3}, {c2}, {c2,c3} — the union is all
    # three, the intersection empty. The first cautious APPROXIMATION is a
    # full answer set, so getting [] back proves refinement ran to the end.
    program = ASPProgram()
    X = Variable("X")
    choice = Choice(Color(x=X), condition=Dom(x=X)).at_least(1).at_most(2)
    program.fact(*[Dom(x=i) for i in (1, 2, 3)])
    program.choose(choice)
    program.forbid(Color(x=1), Color(x=2))
    return program


def test_cautious_is_the_final_refinement_not_the_first() -> None:
    result = build().cautious()
    assert isinstance(result, CautiousConsequences)
    assert result.statistics is not None and "wall_time" in result.statistics  # the eager verb keeps the snapshot
    assert isinstance(result, Consequences)
    assert not isinstance(result, BraveConsequences)
    assert result.complete
    assert result.atoms(Color) == []  # the true (empty) intersection


def test_brave_is_the_union() -> None:
    result = build().brave()
    assert isinstance(result, BraveConsequences)
    assert result.complete
    assert sorted(a["x"].value for a in result.atoms(Color)) == [1, 2, 3]


def test_cautious_finds_forced_atoms() -> None:
    # forced is derived in every answer set: the hint-generator question
    program = build()
    program.when(Color(x=ANY)).derive(Forced())
    result = program.cautious()
    assert result is not None
    assert len(result.atoms(Forced)) == 1


def test_path_keeps_the_receipts() -> None:
    # Approximations are retained; entries are claim-free AtomCollections
    # (not Models, not Consequences); path[0] is in fact an answer set —
    # for brave, a subset of the union with at least one atom
    result = build().brave()
    assert result is not None
    assert len(result.path) >= 2  # the union is no single answer set
    assert all(type(entry) is AtomCollection for entry in result.path)
    first = {a["x"].value for a in result.path[0].atoms(Color)}
    assert 1 <= len(first) <= 2  # a genuine answer set of this program...
    assert first != {1, 2}  # ...which the forbid(c1, c2) constraint would exclude
    # brave approximations grow monotonically to the final answer
    seen: set[int] = set()
    for entry in result.path:
        step = {a["x"].value for a in entry.atoms(Color)}
        assert seen <= step
        seen = step
    assert seen == {1, 2, 3}


def test_iterations_bound_returns_honest_partial() -> None:
    # One refinement step: both modes return path[0] flagged incomplete.
    # Brave partial: every atom certified possible (in the true union).
    # Cautious partial: every ABSENT atom certified not-forced.
    brave = build().brave(max_iterations=1)
    assert isinstance(brave, BraveConsequences)
    assert not brave.complete
    assert len(brave.path) == 1
    assert {a["x"].value for a in brave.atoms(Color)} <= {1, 2, 3}

    cautious = build().cautious(max_iterations=1)
    assert isinstance(cautious, CautiousConsequences)
    assert not cautious.complete
    present = {a["x"].value for a in cautious.atoms(Color)}
    absent = {1, 2, 3} - present
    assert absent  # some atom is absent, certified not-forced — true here (intersection is empty)


def test_bound_landing_on_the_last_step_is_still_incomplete() -> None:
    # Completeness is a proof, not a coincidence: cap exactly at the natural
    # step count and the result still reports incomplete
    unbounded = build().brave()
    assert unbounded is not None and unbounded.complete
    capped = build().brave(max_iterations=len(unbounded.path))
    assert capped is not None
    assert not capped.complete
    assert {a["x"].value for a in capped.atoms(Color)} == {1, 2, 3}  # same atoms, weaker claim


def test_unsat_returns_none() -> None:
    P = Predicate.define("p_unsat_c", [])
    program = ASPProgram()
    program.fact(P())
    program.forbid(P())
    assert program.cautious() is None
    assert program.brave() is None


def test_consequences_respect_show_config() -> None:
    # Dom is hidden: trivially in every answer set, absent from the result —
    # and asking for it teaches instead of returning a silent []
    result = build().brave()
    assert result is not None
    assert all(type(atom) is not Dom for atom in result.atoms())
    with pytest.raises(ValueError, match=r"dom/1 is hidden.*show\(\) the class"):
        result.atoms(Dom)


def test_grounding_answers_many_questions() -> None:
    # One grounding: enumerate, cautious, brave, enumerate again — the
    # refinement mode never leaks into later solves
    grounded = build().ground()
    assert len(list(grounded.solve())) == 5
    cautious = grounded.cautious()
    assert cautious is not None and cautious.atoms(Color) == []
    brave = grounded.brave()
    assert brave is not None and len(brave.atoms(Color)) == 3
    assert len(list(grounded.solve())) == 5


def test_consequences_under_assumptions() -> None:
    # Assuming color(3) narrows the answer sets: color(3) becomes forced,
    # and the assumption does not persist
    grounded = build().ground()
    result = grounded.cautious(assumptions=[Color(x=3)])
    assert result is not None
    assert sorted(a["x"].value for a in result.atoms(Color)) == [3]
    unassumed = grounded.cautious()
    assert unassumed is not None and unassumed.atoms(Color) == []


def test_sequential_guard_covers_consequences() -> None:
    grounded = build().ground()
    stream = grounded.solve()
    next(iter(stream))
    with pytest.raises(RuntimeError, match="still open"):
        grounded.cautious()
    stream.close()
    assert grounded.cautious() is not None


def test_optimizing_program_rejected() -> None:
    # The refinement would follow the cost descent and give a confidently
    # wrong answer; observer ground truth refuses at the verb
    program = build()
    program.raw_asp("#minimize{ 1,X : color(X) }.", predicates=[Color])
    with pytest.raises(ValueError, match="cost-descent"):
        program.cautious()


def test_negative_bounds_rejected() -> None:
    grounded = build().ground()
    with pytest.raises(ValueError, match="timeout"):
        grounded.brave(timeout=-1)
    with pytest.raises(ValueError, match="max_iterations"):
        grounded.cautious(max_iterations=-1)


def test_optimizing_grounding_refuses_every_non_optimize_verb() -> None:
    # Static detection covers the whole verb surface, with per-verb remedies
    program = build()
    program.raw_asp("#minimize{ 1,X : color(X) }.", predicates=[Color])
    grounded = program.ground()
    with pytest.raises(ValueError, match="cost-descent"):
        grounded.cautious()
    with pytest.raises(ValueError, match="cost-descent"):
        grounded.brave()
    with pytest.raises(ValueError, match=r"cost-descent.*ignore_optimization=True"):
        grounded.brave_iter()  # the wall names the flag that lifts it
    with pytest.raises(ValueError, match=r"optimize\(\)"):
        grounded.solve()


def test_ignore_optimization_refines_over_all_answer_sets() -> None:
    # The optimizing twin of build(): with the objective ignored, both
    # refinements answer over ALL answer sets — the plain program's known
    # union {1,2,3} and empty intersection
    program = build()
    program.raw_asp("#minimize{ 1,X : color(X) }.", predicates=[Color])
    grounded = program.ground()
    union = grounded.brave(ignore_optimization=True)
    assert union is not None and union.complete
    assert sorted(atom["x"].value for atom in union.atoms(Color)) == [1, 2, 3]
    forced = grounded.cautious(ignore_optimization=True)
    assert forced is not None and forced.complete
    assert forced.atoms(Color) == []
    # The iterator twins take the flag too, and nothing leaks: a later
    # optimize() on the SAME grounding still optimizes
    steps = grounded.cautious_iter(ignore_optimization=True)
    assert list(steps)[-1].atoms(Color) == []
    best = grounded.optimize()
    assert best is not None and best.cost == (1,)  # at_least(1) forces one color
    # And the flag still requires an objective to ignore
    with pytest.raises(ValueError, match="Nothing to ignore"):
        build().cautious(ignore_optimization=True)
    with pytest.raises(ValueError, match="Nothing to ignore"):
        build().ground().brave_iter(ignore_optimization=True)


def test_steps_primitive_adaptive_early_exit() -> None:
    # The point of the primitive: stop the moment YOUR question is answered.
    # Here: "is color(1) forced?" — certified no as soon as it drops out
    grounded = build().ground()
    answer = None
    steps = grounded.cautious_iter()
    for approximation in steps:
        if 1 not in {a["x"].value for a in approximation.atoms(Color)}:
            answer = "not forced"  # absence in ANY approximation is a certificate
            break
    steps.close()
    assert answer == "not forced"
    assert not steps.exhausted  # we stopped; the refinement didn't finish


def test_steps_natural_exhaustion_is_the_answer() -> None:
    steps = build().ground().brave_iter()
    approximations = list(steps)
    assert steps.exhausted
    assert steps.finished
    assert steps.steps_taken == len(approximations)
    assert {a["x"].value for a in approximations[-1].atoms(Color)} == {1, 2, 3}


def test_steps_register_with_the_sequential_guard() -> None:
    grounded = build().ground()
    steps = grounded.brave_iter()
    next(iter(steps))
    with pytest.raises(RuntimeError, match="still open"):
        grounded.solve()
    with pytest.raises(RuntimeError, match="still open"):
        grounded.cautious()
    steps.close()
    assert len(list(grounded.solve())) == 5  # freed


def test_steps_already_consumed_guard() -> None:
    steps = build().ground().brave_iter()
    list(steps)
    with pytest.raises(RuntimeError, match="already consumed"):
        iter(steps)


def test_steps_unsat_yields_nothing_and_proves_it() -> None:
    P = Predicate.define("p_unsat_s", [])
    program = ASPProgram()
    program.fact(P())
    program.forbid(P())
    steps = program.ground().cautious_iter()
    assert list(steps) == []
    assert steps.exhausted  # proven UNSAT, not interrupted


def test_steps_work_as_context_manager() -> None:
    grounded = build().ground()
    with grounded.cautious_iter() as steps:
        next(iter(steps))
    assert steps.finished
    assert len(list(grounded.solve())) == 5  # the with-block freed the grounding


def test_refinements_carry_statistics() -> None:
    # Unification dividend: refinements snapshot statistics like any search
    grounded = build().ground()
    steps = grounded.brave_iter()
    list(steps)
    assert steps.statistics is not None
    assert steps.statistics["wall_time"] > 0
    assert steps.satisfiable is True


def test_raw_asp_contract_applies_to_refinements() -> None:
    # An undeclared raw-produced atom fails loudly on refinement paths too
    Declared = Predicate.define("declared_r", ["x"])
    program = ASPProgram()
    program.fact(Declared(x=1))
    program.raw_asp("sneaky(1..2).")  # deliberately undeclared
    with pytest.raises(ValueError, match="never declared"):
        program.brave()


def _pigeonhole() -> ASPProgram:
    # 14 pigeons, 13 holes: UNSAT, and the proof takes clasp far longer
    # than the test deadlines below — a deterministic timeout trigger
    Pigeon = Predicate.define("pigeon", ["p"], show=False)
    Assign = Predicate.define("assign", ["p", "h"])
    program = ASPProgram()
    P, P2, H = Variable("P"), Variable("P2"), Variable("H")
    program.fact(*[Pigeon(p=i) for i in range(1, 15)])
    program.when(Pigeon(p=P)).derive(Choice(Assign(p=P, h=RangePool(1, 13))).exactly(1))
    program.forbid(Assign(p=P, h=H), Assign(p=P2, h=H), P < P2)
    return program


def test_cautious_timeout_before_first_approximation_raises() -> None:
    # With no models seen, a cautious partial's superset bound is every
    # atom — unrepresentable, so it raises with the teaching message
    with pytest.raises(TimeoutError, match="Raise the timeout"):
        _pigeonhole().cautious(timeout=0.05)


def test_brave_timeout_with_zero_emissions_returns_empty_partial() -> None:
    # A brave partial with nothing seen is representable: the empty set,
    # nothing certified possible yet
    result = _pigeonhole().brave(timeout=0.05)
    assert isinstance(result, BraveConsequences)
    assert not result.complete
    assert result.timed_out is True  # the deadline (not a cap) cut it short
    assert result.path == ()
    assert result.atoms() == []


def test_steps_timeout_leaves_consistent_state() -> None:
    grounded = _pigeonhole().ground()
    steps = grounded.brave_iter(timeout=0.05)
    with pytest.raises(TimeoutError, match="before its first approximation"):
        list(steps)  # zero yields: the message claims no bound it does not have
    assert steps.finished  # the stream ended, loudly
    assert not steps.exhausted  # a timed-out search never claims exhaustion
    assert steps.satisfiable is None  # nothing was learned either way
    assert steps.steps_taken == 0
    assert steps.statistics is not None  # the snapshot still lands
    # The grounding is freed: the next search begins without a guard error
    grounded.cautious_iter(timeout=0.05).close()


def test_abandon_mid_refinement_frees_the_grounding() -> None:
    grounded = build().ground()
    steps = grounded.cautious_iter()
    next(iter(steps))
    grounded.abandon()
    assert steps.finished
    assert steps.statistics is not None  # early close still snapshots
    assert len(list(grounded.solve())) == 5


def test_refinement_timeout_mid_stream_raises() -> None:
    # Refinement ALWAYS raises on timeout, even with approximations in
    # hand — they are scaffolding, not answers. This program refines
    # quickly at first (free atoms union in fast) but cannot finish: the
    # last atom's impossibility needs a slow pigeonhole UNSAT proof.
    Free = Predicate.define("free_mid", [])
    Hard = Predicate.define("hard_mid", [])
    PigeonM = Predicate.define("pigeon_mid", ["p"], show=False)
    AssignM = Predicate.define("assign_mid", ["p", "h"])
    program = ASPProgram()
    P, P2, H = Variable("P"), Variable("P2"), Variable("H")
    program.choose(Choice(Free()))
    program.fact(*[PigeonM(p=i) for i in range(1, 15)])
    program.when(PigeonM(p=P)).derive(Choice(AssignM(p=P, h=RangePool(1, 13))).at_most(1))
    program.forbid(AssignM(p=P, h=H), AssignM(p=P2, h=H), P < P2)
    # hard_mid needs all 14 pigeons placed in 13 distinct holes: impossible,
    # but proving that is the slow step
    program.when(Count((P, H), condition=AssignM(p=P, h=H)) >= 14).derive(Hard())
    # The deadline window is two-sided: the FIRST approximation must land
    # inside it (steps_taken >= 1) while the proof must not finish — the
    # instance size guards the slow side, the deadline gives the fast side
    # generous slack for a loaded machine
    steps = program.ground().brave_iter(timeout=0.3)
    with pytest.raises(TimeoutError, match="did not finish"):
        list(steps)
    assert steps.steps_taken >= 1  # approximations were in hand — raised anyway
    assert not steps.exhausted
    assert steps.statistics is not None
