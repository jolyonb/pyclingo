"""
Tests for the optimization solve verbs: optimize() and optimize_iter() and
their bound / strategy / all_optima / assumption / timeout options — every
case that actually runs a search and asserts on the optima or costs it finds.
"""

from itertools import islice

import pytest

from pyclingo import (
    ANY,
    ASPProgram,
    Choice,
    CostedModel,
    Optimum,
    OptStrategy,
    Predicate,
    RangePool,
    Variable,
)

Pick = Predicate.define("pick", ["x"])


def build_knapsack() -> ASPProgram:
    # Choose at least one of picks 1..4, minimize the sum: optimum is {1}
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).add(Pick(x=4)).at_least(1))
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


def test_ignore_optimization_enumerates_every_answer_set() -> None:
    # The knapsack has 15 answer sets (any non-empty pick set); optimize()
    # collapses them to the optimum, ignore_optimization streams them all,
    # cost-free — and a later optimize() on the SAME grounding still
    # optimizes (opt_mode never leaks between searches)
    grounded = build_knapsack().ground()
    with pytest.raises(ValueError, match="ignore_optimization=True"):
        grounded.solve()  # the wall names the flag
    models = list(grounded.solve(ignore_optimization=True))
    assert len(models) == 15
    best = grounded.optimize()
    assert best is not None and best.cost == (1,)
    # The program-level sugar takes the flag too
    assert len(list(build_knapsack().solve(ignore_optimization=True))) == 15


def test_ignore_optimization_requires_an_objective() -> None:
    program = ASPProgram()
    program.fact(Pick(x=1))
    with pytest.raises(ValueError, match="Nothing to ignore"):
        program.solve(ignore_optimization=True)
    with pytest.raises(ValueError, match="Nothing to ignore"):
        program.ground().solve(ignore_optimization=True)


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
    # 14 pigeons, 13 holes with an objective: UNSAT and slow, so a short
    # deadline reliably lands before any model exists
    program = ASPProgram()
    P, P2, H = Variable("P"), Variable("P2"), Variable("H")
    program.fact(*[PigeonOpt(p=i) for i in range(1, 15)])
    program.when(PigeonOpt(p=P)).derive(Choice(AssignOpt(p=P, h=RangePool(1, 13))).exactly(1))
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
    assert steps.models_yielded == 1
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
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).at_least(1).at_most(1))
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


def test_usc_strategy_finds_the_same_optimum() -> None:
    grounded = build_knapsack().ground()
    bb = grounded.optimize(strategy=OptStrategy.BB)
    usc = grounded.optimize(strategy=OptStrategy.USC)
    default = grounded.optimize()  # strategy resets to BB per entry
    assert bb is not None and usc is not None and default is not None
    assert bb.cost == usc.cost == default.cost == (1,)
    assert bb.proven and usc.proven and default.proven


def build_three_optima() -> ASPProgram:
    # Exactly one pick, every choice costs 1: three optimal models
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).at_least(1).at_most(1))
    program.penalize(Pick(x=X))
    return program


def test_all_optima_collects_every_certified_model() -> None:
    result = build_three_optima().optimize(all_optima=True)
    assert result is not None
    assert result.proven and result.complete
    assert result.optima is not None and len(result.optima) == 3
    assert all(model.proven for model in result.optima)
    assert all(model.cost == (1,) for model in result.optima)
    picks = sorted(model.atoms(Pick)[0]["x"].value for model in result.optima)
    assert picks == [1, 2, 3]
    # The descent prefix is unproven; the certified tail is the optima
    assert not result.path[0].proven


def test_plain_optimize_has_no_optima_but_keeps_the_path() -> None:
    result = build_knapsack().optimize()
    assert result is not None and result.proven and result.complete
    assert result.optima is None  # not asked
    assert result.path  # the receipts remain
    assert all(not model.proven for model in result.path)  # plain emissions are uncertified


def test_uniqueness_via_the_certified_stream() -> None:
    unique = build_knapsack().optimize(all_optima=True)
    assert unique is not None and unique.optima is not None
    assert len(unique.optima) == 1

    # The islice form: stop as soon as a second certified optimum appears
    steps = build_three_optima().ground().optimize_iter(all_optima=True)
    certified = list(islice((m for m in steps if m.proven), 2))
    steps.close()
    assert len(certified) == 2  # not unique, proven with two models' work
    assert not steps.exhausted


def test_all_optima_unsat_returns_none() -> None:
    program = build_three_optima()
    program.forbid(Pick(x=ANY))
    assert program.optimize(all_optima=True) is None


def test_bound_starts_the_search_at_a_known_cost() -> None:
    grounded = build_knapsack().ground()
    bounded = grounded.optimize(bound=3)
    assert bounded is not None and bounded.proven
    assert bounded.cost == (1,)  # same optimum, shorter search
    # A too-tight bound is reported as unsatisfiable — clasp cannot
    # distinguish it from a genuinely unsatisfiable program
    assert grounded.optimize(bound=0) is None
    # and the bound never leaks into the next search
    unbounded = grounded.optimize()
    assert unbounded is not None and unbounded.cost == (1,)


def test_multi_priority_bound_is_priority_keyed() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).at_least(1).at_most(2))
    program.minimize(1, X, condition=Pick(x=X), priority=2)
    program.minimize(X, condition=Pick(x=X), priority=1)
    grounded = program.ground()
    assert grounded.optimization_levels == (2, 1)
    result = grounded.optimize(bound={2: 1, 1: 1})
    assert result is not None and result.proven
    assert result.cost == (1, 1)
    # A bare int is ambiguous with two tiers; a trailing-only key is
    # inexpressible (clasp bounds are a leading prefix) so it drops
    with pytest.raises(ValueError, match="name the tier"):
        grounded.optimize(bound=1)
    trailing_only = grounded.optimize(bound={1: 1})  # no leading cover: no hint
    assert trailing_only is not None and trailing_only.cost == (1, 1)


def test_optima_mode_never_leaks_between_searches() -> None:
    # optN is stated per entry: a plain optimize() after all_optima sees
    # only uncertified descent emissions
    grounded = build_three_optima().ground()
    everything = grounded.optimize(all_optima=True)
    assert everything is not None and everything.optima is not None and len(everything.optima) == 3
    plain = grounded.optimize()
    assert plain is not None and plain.proven
    assert plain.optima is None
    assert all(not model.proven for model in plain.path)
    again = grounded.optimize(all_optima=True)
    assert again is not None and again.optima is not None and len(again.optima) == 3


def test_all_optima_re_emits_the_descents_final_model() -> None:
    # The descent ends on an optimal model (uncertified — the proof lands
    # after it); the re-enumeration emits that same model again with its
    # certificate. Filtering on .proven sees each optimum exactly once.
    result = build_three_optima().optimize(all_optima=True)
    assert result is not None and result.optima is not None
    unproven = [m for m in result.path if not m.proven]
    assert unproven  # a descent happened
    last_descent = sorted(str(a) for a in unproven[-1].atoms())
    certified_atomsets = [sorted(str(a) for a in m.atoms()) for m in result.optima]
    assert last_descent in certified_atomsets  # the same model, now certified
    assert len(result.optima) == len({tuple(a) for a in certified_atomsets})  # certified are distinct


def test_bound_keys_are_best_effort_hints() -> None:
    # A bound is a pruning hint: keys on surviving tiers apply, everything
    # else drops silently — the optimum is unchanged either way
    grounded = build_knapsack().ground()  # one ground tier: priority 0
    assert grounded.optimization_levels == (0,)
    applied = grounded.optimize(bound={0: 1, 2: 0})  # 2 names nothing: ignored
    assert applied is not None and applied.cost == (1,)
    assert [m.cost for m in applied.path] == [(1,)]  # tier-0 bound still pruned
    assert grounded.optimize(bound={0: 1}) is not None
    assert grounded.optimize(bound=1) is not None  # single tier: bare int fine


def test_optimum_levels_keys_cost_by_priority() -> None:
    # The cost tuple is positional (highest tier first); levels reads it
    # by priority name
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(X, condition=Pick(x=X), priority=2)
    program.minimize(1, X, condition=Pick(x=X), priority=1)
    result = program.optimize()
    assert result is not None and result.proven
    assert result.cost == (1, 1)  # pick(1) alone: value 1, count 1
    assert result.levels == {2: 1, 1: 1}
    assert result.timed_out is False
    assert result.statistics is not None and "wall_time" in result.statistics


def test_optimize_timeout_with_model_in_hand_reports_timed_out() -> None:
    # 14 pigeons, 13 holes, but a pigeon may stay unplaced at cost 1: the
    # descent to one-unplaced is instant, and proving zero-unplaced
    # impossible is the classic hard pigeonhole proof — a deterministic
    # optimization timeout with a genuine solution in hand
    Pigeon = Predicate.define("pigeon_to", ["p"], show=False)
    Assign = Predicate.define("assign_to", ["p", "h"])
    Unplaced = Predicate.define("unplaced_to", ["p"], show=False)
    program = ASPProgram()
    P, P2, H = Variable("P"), Variable("P2"), Variable("H")
    program.fact(*[Pigeon(p=i) for i in range(1, 15)])
    program.when(Pigeon(p=P)).derive(Choice(Assign(p=P, h=RangePool(1, 13))).at_most(1))
    program.forbid(Assign(p=P, h=H), Assign(p=P2, h=H), P < P2)
    program.when(Pigeon(p=P), ~Assign(p=P, h=ANY)).derive(Unplaced(p=P))
    program.minimize(1, P, condition=Unplaced(p=P))
    result = program.optimize(timeout=0.5)
    assert result is not None  # a genuine solution is in hand
    assert result.cost == (1,)  # descended to the true optimum...
    assert result.timed_out is True  # ...but the deadline cut off its proof
    assert result.proven is False
