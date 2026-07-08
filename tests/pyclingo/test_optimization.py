"""
Tests for #minimize/#maximize authoring: rendering (weight@priority,
tuples, conditions), element scoping (a directive has no rule body, so
everything binds inside the element), and end-to-end behavior probed
against clasp (same-priority statements merge additively; maximize
reports negated costs; priorities are ordinal keys with free gaps).
"""

import clingo
import pytest

from pyclingo import (
    ANY,
    ASPProgram,
    Choice,
    ConditionalLiteral,
    CostedModel,
    Count,
    Optimum,
    OptStrategy,
    Predicate,
    RangePool,
    SolveResult,
    String,
    Variable,
)
from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel


def optimal_cost(program: ASPProgram) -> list[int]:
    """Ground and fully descend via clingo directly; cost plumbing arrives with the solving verbs."""
    ctl = clingo.Control(logger=lambda c, m: None)
    solve_config = ctl.configuration.solve
    assert isinstance(solve_config, clingo.Configuration)
    solve_config.models = 0
    ctl.add("base", [], program.render())
    ctl.ground([("base", [])])
    cost: list[int] = []
    with ctl.solve(yield_=True) as h:
        for model in h:
            cost = list(model.cost)
    return cost


Island = Predicate.define("island", ["loc", "size"], show=False)
Pick = Predicate.define("pick", ["x"])


def test_minimize_renders_weight_tuple_condition() -> None:
    program = ASPProgram()
    Size, C = Variable("Size"), Variable("C")
    program.fact(Island(loc=1, size=3))
    program.minimize(Size, C, condition=Island(loc=C, size=Size))
    assert "#minimize{ Size, C : island(C, Size) }." in program.render()


def test_priority_renders_at_form_and_zero_is_bare() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.fact(Pick(x=1))
    program.minimize(1, X, condition=Pick(x=X), priority=2)
    program.minimize(X, condition=Pick(x=X))  # priority 0: no @
    rendered = program.render()
    assert "#minimize{ 1@2, X : pick(X) }." in rendered
    assert "#minimize{ X : pick(X) }." in rendered


def test_maximize_renders() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.fact(Pick(x=1))
    program.maximize(X, condition=Pick(x=X))
    assert "#maximize{ X : pick(X) }." in program.render()


def test_unbound_element_variable_rejected() -> None:
    # No rule body exists to bind W: it must bind inside the element
    program = ASPProgram()
    W, X = Variable("W"), Variable("X")
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.minimize(W, X, condition=Pick(x=X))


def test_singleton_element_variable_rejected() -> None:
    program = ASPProgram()
    X, Y = Variable("X"), Variable("Y")
    Pair = Predicate.define("pair_opt", ["a", "b"])
    with pytest.raises(ValueError, match="Singleton variable"):
        program.minimize(X, condition=Pair(a=X, b=Y))


def test_weight_types_validated() -> None:
    program = ASPProgram()
    with pytest.raises(TypeError, match="got str"):
        program.minimize("three", condition=Pick(x=ANY))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer-valued"):
        program.minimize(String("three"), condition=Pick(x=ANY))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="priority must be an int"):
        program.minimize(1, condition=Pick(x=ANY), priority="high")  # type: ignore[arg-type]


def test_aggregate_condition_rejected() -> None:
    # ConditionedElement's shared guard covers optimization elements too
    program = ASPProgram()
    X, K = Variable("X"), Variable("K")
    with pytest.raises(ValueError, match="Aggregates cannot appear inside optimization conditions"):
        program.minimize(1, X, condition=[Pick(x=X), K == Count(X, condition=Pick(x=X))])


def test_grounds_cleanly() -> None:
    # The rendered directive is real gringo: grounding succeeds
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)))
    program.minimize(X, condition=Pick(x=X))
    grounded = program.ground()
    assert "#minimize" in grounded.text


def test_statements_share_one_tuple_set() -> None:
    # All optimization statements contribute to ONE tuple set: identical
    # tuples count once, distinct tuples sum
    X = Variable("X")

    duplicated = ASPProgram()
    duplicated.fact(Pick(x=1), Pick(x=2))
    duplicated.minimize(1, X, condition=Pick(x=X))
    duplicated.minimize(1, X, condition=Pick(x=X))  # identical tuples: dedup
    assert optimal_cost(duplicated) == [2]

    distinct = ASPProgram()
    distinct.fact(Pick(x=1), Pick(x=2))
    distinct.minimize(1, X, String("a"), condition=Pick(x=X))
    distinct.minimize(1, X, String("b"), condition=Pick(x=X))  # distinct tuples: sum
    assert optimal_cost(distinct) == [4]


def test_priority_gaps_are_free() -> None:
    # Priorities are ordinal keys: @3/@1 behaves exactly like dense levels
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(1, X, condition=Pick(x=X), priority=3)
    program.minimize(X, condition=Pick(x=X), priority=1)
    assert optimal_cost(program) == [1, 1]  # two entries, highest priority first, no phantom @2


def test_explicit_zero_renders_bare() -> None:
    # priority=0 and no priority are the same statement, byte-identical:
    # @0 is never rendered, so the two spellings cannot diverge
    explicit = ASPProgram()
    bare = ASPProgram()
    X = Variable("X")
    for program in (explicit, bare):
        program.fact(Pick(x=1))
    explicit.minimize(1, X, condition=Pick(x=X), priority=0)
    bare.minimize(1, X, condition=Pick(x=X))
    assert explicit.render() == bare.render()


def test_bare_statements_sit_at_priority_zero() -> None:
    # A statement without priority= IS priority 0: mixing bare and
    # prioritized statements creates distinct levels, bare least important
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(1, X, condition=Pick(x=X), priority=2)
    program.minimize(X, condition=Pick(x=X))  # bare: level 0
    assert optimal_cost(program) == [1, 1]  # [level 2, level 0], count then sum


def test_native_directive_refuses_solve_and_consequences() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(X, condition=Pick(x=X))
    with pytest.raises(ValueError, match=r"optimize\(\)"):
        program.solve()
    with pytest.raises(ValueError, match="cost-descent"):
        program.cautious()


def test_weak_constraint_in_raw_detected() -> None:
    # :~ is #minimize in disguise; the scan must catch it with no
    # #minimize token anywhere in the text
    program = ASPProgram()
    program.fact(Pick(x=1))
    program.raw_asp(":~ pick(X). [X@1, X]")
    with pytest.raises(ValueError, match=r"optimize\(\)"):
        program.solve()


def test_tokens_in_comments_and_strings_do_not_count() -> None:
    program = ASPProgram()
    program.fact(Pick(x=1))
    program.raw_asp('% a note about #minimize\n%* block :~ comment *%\nnote("#maximize inside a string").')
    Note = Predicate.define("note", ["t"])
    program.raw_asp("", predicates=[Note])
    result = program.solve()  # not an optimizing program
    assert len(list(result)) == 1


def test_project_shown_refuses_optimization() -> None:
    # clasp warns optimization may depend on enumeration order under
    # projection; the combination is refused at ground
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(X, condition=Pick(x=X))
    program.project_shown = True
    with pytest.raises(ValueError, match="enumeration order"):
        program.ground()


def test_runtime_backstop_catches_unscanned_costs() -> None:
    # Defense in depth: a costed model reaching the models-mode generator
    # raises even when static detection saw nothing. Constructed directly,
    # since every library path is already guarded statically.
    ctl = clingo.Control(logger=lambda c, m: None)
    solve_config = ctl.configuration.solve
    assert isinstance(solve_config, clingo.Configuration)
    solve_config.models = 0
    ctl.add("base", [], "pick(1..2). #minimize{ 1,X : pick(X) }.")
    ctl.ground([("base", [])])
    handler = ClingoMessageHandler("", stop_on_level=LogLevel.CRITICAL)
    result = SolveResult(ctl, {("pick", 1): Pick}, 0, handler)
    with pytest.raises(ValueError, match="carries a cost"):
        list(result)


def build_knapsack() -> ASPProgram:
    # Choose at least one of picks 1..4, minimize the sum: optimum is {1}
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).add(Pick(x=4)).at_least(1))
    program.minimize(X, condition=Pick(x=X))
    return program


def test_optimize_finds_the_proven_optimum() -> None:
    result = build_knapsack().optimize()
    assert isinstance(result, Optimum)
    assert isinstance(result, CostedModel)  # an optimum IS an answer set
    assert result.proven
    assert result.cost == (1,)
    assert [a["x"].value for a in result.atoms(Pick)] == [1]
    # The descent receipts: genuine models, strictly improving costs
    assert all(isinstance(step, CostedModel) for step in result.path)
    costs = [step.cost for step in result.path]
    assert costs == sorted(costs, reverse=True)
    assert len(set(costs)) == len(costs)
    assert result.path[-1].cost == result.cost


def test_optimize_nothing_to_optimize_rejected() -> None:
    program = ASPProgram()
    program.fact(Pick(x=1))
    with pytest.raises(ValueError, match="Nothing to optimize"):
        program.optimize()


def test_optimize_unsat_returns_none() -> None:
    program = build_knapsack()
    program.forbid(Pick(x=ANY))  # picking is mandatory and forbidden
    assert program.optimize() is None


def test_optimize_max_iterations_returns_best_so_far() -> None:
    result = build_knapsack().optimize(max_iterations=1)
    assert result is not None
    assert not result.proven  # one step: a genuine solution, no proof
    assert len(result.path) == 1
    assert result.cost == result.path[0].cost


def test_optimize_cap_landing_on_optimum_stays_unproven() -> None:
    full = build_knapsack().optimize()
    assert full is not None and full.proven
    capped = build_knapsack().optimize(max_iterations=len(full.path))
    assert capped is not None
    assert capped.cost == full.cost  # same best model
    assert not capped.proven  # but optimality was never proven


PigeonOpt = Predicate.define("pigeon_opt", ["p"], show=False)
AssignOpt = Predicate.define("assign_opt", ["p", "h"])


def _slow_unsat_optimizing() -> ASPProgram:
    # 12 pigeons, 11 holes with an objective: UNSAT and slow, so a short
    # deadline reliably lands before any model exists
    program = ASPProgram()
    P, P2, H = Variable("P"), Variable("P2"), Variable("H")
    program.fact(*[PigeonOpt(p=i) for i in range(1, 13)])
    program.when(PigeonOpt(p=P), let=Choice(AssignOpt(p=P, h=RangePool(1, 11))).exactly(1))
    program.forbid(AssignOpt(p=P, h=H), AssignOpt(p=P2, h=H), P < P2)
    program.minimize(1, P, condition=AssignOpt(p=P, h=ANY))
    return program


def test_optimize_timeout_before_any_model_raises() -> None:
    with pytest.raises(TimeoutError, match="no model within"):
        _slow_unsat_optimizing().optimize(timeout=0.05)


def test_descend_early_exit_keeps_best_so_far() -> None:
    grounded = build_knapsack().ground()
    steps = grounded.optimize_iter()
    best = next(iter(steps))
    steps.close()
    assert best.cost  # a genuine costed solution in hand
    assert not steps.exhausted  # optimality unproven: we stopped
    assert steps.models_seen == 1
    assert steps.statistics is not None
    result = grounded.optimize()  # the grounding is free for the next search
    assert result is not None and result.proven


def test_optimize_under_assumptions() -> None:
    grounded = build_knapsack().ground()
    result = grounded.optimize(assumptions=[Pick(x=3)])
    assert result is not None
    assert result.cost == (3,)  # pick(3) alone is the cheapest model containing it
    unassumed = grounded.optimize()
    assert unassumed is not None and unassumed.cost == (1,)  # nothing persists


def test_maximize_optimum_reports_negated_cost() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).at_least(1).at_most(1))
    program.maximize(X, condition=Pick(x=X))
    result = program.optimize()
    assert result is not None and result.proven
    assert [a["x"].value for a in result.atoms(Pick)] == [3]
    assert result.cost == (-3,)  # clasp minimizes the negation; lower is better


def test_sequential_guard_covers_descent() -> None:
    grounded = build_knapsack().ground()
    steps = grounded.optimize_iter()
    next(iter(steps))
    with pytest.raises(RuntimeError, match="still open"):
        grounded.optimize()
    steps.close()
    assert grounded.optimize() is not None


def test_optimize_iter_timeout_before_any_model_raises() -> None:
    # Empty-handed, a quiet stop would read as unsatisfiable; with a best
    # in hand a timeout is quiet — the raise happens exactly when there is
    # nothing usable to keep
    program = _slow_unsat_optimizing()
    steps = program.ground().optimize_iter(timeout=0.05)
    with pytest.raises(TimeoutError, match="no model within"):
        list(steps)
    assert steps.finished
    assert not steps.exhausted


def test_penalize_renders_weak_constraint() -> None:
    program = ASPProgram()
    C, S = Variable("C"), Variable("S")
    Island = Predicate.define("island_wc", ["loc", "size"])
    program.fact(Island(loc=1, size=3))
    program.penalize(Island(loc=C, size=S), weight=S, terms=[C], priority=2)
    assert ":~ island_wc(C, S). [S@2, C]" in program.render()
    program2 = ASPProgram()
    program2.fact(Island(loc=1, size=3))
    program2.penalize(Island(loc=C, size=S), weight=S, terms=[C])  # bare priority
    assert ":~ island_wc(C, S). [S, C]" in program2.render()


def test_penalize_is_minimize_in_disguise() -> None:
    # The two spellings share one tuple set: identical tuples dedup, and
    # the optima agree
    X = Variable("X")

    def build_with(spelling: str) -> ASPProgram:
        program = ASPProgram()
        program.fact(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).at_least(1))
        if spelling == "penalize":
            program.penalize(Pick(x=X), weight=X, terms=[X])
        else:
            program.minimize(X, X, condition=Pick(x=X))
        return program

    assert optimal_cost(build_with("penalize")) == optimal_cost(build_with("minimize")) == [1]

    both = ASPProgram()
    both.fact(Pick(x=1), Pick(x=2))
    both.penalize(Pick(x=X), weight=1, terms=[X])
    both.minimize(1, X, condition=Pick(x=X))  # identical tuples across spellings
    assert optimal_cost(both) == [2]


def test_penalize_detected_as_optimizing() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.penalize(Pick(x=X), weight=X, terms=[X])
    with pytest.raises(ValueError, match=r"optimize\(\)"):
        program.solve()
    result = program.optimize()
    assert result is not None and result.proven
    assert result.cost == (1,)


def test_penalize_scoping_is_rule_shaped() -> None:
    # The body binds like a rule body; weight/terms must be bound by it
    program = ASPProgram()
    W, X = Variable("W"), Variable("X")
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.penalize(Pick(x=X), weight=W, terms=[X])
    with pytest.raises(ValueError, match="Singleton variable"):
        Pair = Predicate.define("pair_wc", ["a", "b"])
        program.penalize(Pair(a=X, b=Variable("Y")), weight=1, terms=[X])


def test_penalize_weight_types_validated() -> None:
    program = ASPProgram()
    with pytest.raises(TypeError, match="integer-valued"):
        program.penalize(Pick(x=ANY), weight=String("w"))
    with pytest.raises(TypeError, match="priority must be an int"):
        program.penalize(Pick(x=ANY), weight=1, priority="high")  # type: ignore[arg-type]


def test_penalize_defaults_charge_per_match() -> None:
    # The default tuple is the conditions' variables, written out in the
    # render: each ground match charges separately (gringo's bare tuple
    # would silently collapse them all into one charge)
    program = ASPProgram()
    X = Variable("X")
    program.fact(Pick(x=1), Pick(x=2), Pick(x=3))
    program.penalize(Pick(x=X))
    assert ":~ pick(X). [1, X]" in program.render()
    assert optimal_cost(program) == [3]  # one charge per match


def test_penalize_empty_terms_collapse_deliberately() -> None:
    # terms=[] is the explicit opt-in to gringo's single-charge semantics;
    # the singleton lint pushes the condition variable to ANY, which reads
    # correctly: "if any pick exists, charge once"
    program = ASPProgram()
    program.fact(Pick(x=1), Pick(x=2), Pick(x=3))
    program.penalize(Pick(x=ANY), terms=[])
    assert ":~ pick(_). [1]" in program.render()
    assert optimal_cost(program) == [1]  # every match, one charge


def test_penalize_accepts_aggregate_comparisons() -> None:
    # A weak constraint's conditions form a rule body, exactly as in
    # forbid(): aggregate comparisons are legal there
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)))
    program.penalize(Count(X, condition=Pick(x=X)) >= 2, terms=[])
    assert ":~ #count{ X : pick(X) } >= 2. [1]" in program.render()
    result = program.optimize()
    assert result is not None and result.proven
    assert result.cost == (0,)  # the optimum picks at most one, dodging the charge
    assert len(result.atoms(Pick)) <= 1


def test_penalize_requires_conditions() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="at least one condition"):
        program.penalize(weight=1)


def test_choice_in_body_teaches_the_count_spelling() -> None:
    # clingo's body braces are a cardinality test, not a choice; the two
    # meanings get two spellings (Choice for heads, Count comparisons for
    # bodies) and the error teaches the translation
    program = ASPProgram()
    X = Variable("X")
    with pytest.raises(ValueError, match="Count comparison"):
        program.forbid(Choice(Pick(x=X)).at_least(2))
    with pytest.raises(ValueError, match="Count comparison"):
        program.penalize(Choice(Pick(x=X)).at_least(2))  # forbid parity: same teacher


def test_penalize_accepts_conditional_literals() -> None:
    # forbid parity: a CL is a legal body term, and the separator AFTER it
    # is a semicolon (Rule's own rendering rule, shared)
    Cell = Predicate.define("cell_wc", ["x"], show=False)
    Covered = Predicate.define("covered_wc", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(Cell(x=1), Cell(x=2))
    program.fact(Choice(Covered(x=1)).add(Covered(x=2)))
    program.penalize(
        ConditionalLiteral(Covered(x=X), [Cell(x=X), Covered(x=X)]),
        Covered(x=1),
        terms=[],
    )
    assert ":~ covered_wc(X) : cell_wc(X), covered_wc(X); covered_wc(1). [1]" in program.render()
    result = program.optimize()
    assert result is not None and result.proven
    assert result.cost == (0,)  # skip covering everything (or cell 1) and pay nothing


def test_auto_terms_exclude_construct_locals() -> None:
    # The auto-tuple takes only GLOBAL body variables: an aggregate's local
    # X must not leak into the tuple (it would be unsafe there)
    Tag = Predicate.define("tag_at", ["t"])
    program = ASPProgram()
    X, T = Variable("X"), Variable("T")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)), Tag(t=1), Tag(t=2))
    program.penalize(Tag(t=T), Count(X, condition=Pick(x=X)) >= 2)
    assert ":~ tag_at(T), #count{ X : pick(X) } >= 2. [1, T]" in program.render()


def test_usc_strategy_finds_the_same_optimum() -> None:
    grounded = build_knapsack().ground()
    bb = grounded.optimize(strategy=OptStrategy.BB)
    usc = grounded.optimize(strategy=OptStrategy.USC)
    default = grounded.optimize()  # strategy resets to BB per entry
    assert bb is not None and usc is not None and default is not None
    assert bb.cost == usc.cost == default.cost == (1,)
    assert bb.proven and usc.proven and default.proven
