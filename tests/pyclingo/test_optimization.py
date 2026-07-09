"""
Tests for #minimize/#maximize/penalize authoring: rendering (weight@priority,
tuples, conditions), element scoping (a directive has no rule body, so
everything binds inside the element), weight-type and structural validation,
and cost detection — the ground-truth scan that refuses to silently solve an
optimizing program. Optima are probed against clasp only where a rendered
directive's meaning is at stake (same-priority statements merge additively;
maximize reports negated costs; priorities are ordinal keys with free gaps).
"""

import clingo
import pytest

from pyclingo import (
    ANY,
    ASPProgram,
    Choice,
    ConditionalLiteral,
    Count,
    Number,
    Predicate,
    Segment,
    SolveResult,
    String,
    Variable,
)
from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel
from pyclingo.optimization import Optimization, OptimizationDirective, WeakConstraint


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


def build_knapsack() -> ASPProgram:
    # Choose at least one of picks 1..4, minimize the sum: optimum is {1}
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).add(Pick(x=4)).at_least(1))
    program.minimize(X, condition=Pick(x=X))
    return program


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


def test_priority_outside_clingo_range_rejected() -> None:
    # gringo wraps priorities mod 2^32 with no message even at DEBUG —
    # tiers the author placed apart silently merge or reorder. Probed:
    # priority=2**32+5 grounded as tier 5; 2**31 became the LOWEST tier.
    program = ASPProgram()
    X = Variable("X")
    with pytest.raises(ValueError, match="outside clingo's integer range"):
        program.minimize(1, X, condition=Pick(x=X), priority=2**32 + 5)
    with pytest.raises(ValueError, match="outside clingo's integer range"):
        program.penalize(Pick(x=X), priority=2**31)
    program.minimize(1, X, condition=Pick(x=X), priority=2**31 - 1)  # boundary is legal


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
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)))
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
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
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
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(1, X, condition=Pick(x=X), priority=2)
    program.minimize(X, condition=Pick(x=X))  # bare: level 0
    assert optimal_cost(program) == [1, 1]  # [level 2, level 0], count then sum


def test_native_directive_refuses_solve_and_consequences() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(X, condition=Pick(x=X))
    with pytest.raises(ValueError, match=r"optimize\(\)"):
        program.solve()
    with pytest.raises(ValueError, match="cost-descent"):
        program.cautious()


def test_weak_constraint_in_raw_detected() -> None:
    # :~ is #minimize in disguise; the observer sees it with no
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
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
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
        program.choose(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).at_least(1))
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
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
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


def test_penalize_rejects_negative_weight() -> None:
    # A negative weight is legal ASP but rewards the match, inverting the
    # verb's name — a probable sign flip. The objective verbs are the
    # deliberate spelling, and minimize keeps negative weights legal.
    program = ASPProgram()
    X = Variable("X")
    with pytest.raises(ValueError, match="would reward the match"):
        program.penalize(Pick(x=1), weight=-3)
    with pytest.raises(ValueError, match="would reward the match"):
        program.penalize(Pick(x=1), weight=Number(-3))  # caught the same after coercion
    pending = program.when(Pick(x=1))
    with pytest.raises(ValueError, match="would reward the match"):
        pending.penalize(Pick(x=2), weight=-1)
    pending.penalize(Pick(x=2), weight=1)  # the rejected closer left the when() retryable
    program.penalize(Pick(x=X), weight=X)  # a variable weight is unknowable: accepted
    program.minimize(-3, condition=Pick(x=1))  # the deliberate escape stays legal
    assert "#minimize{ -3 : pick(1) }." in program.render()


def test_penalize_defaults_charge_per_match() -> None:
    # The default tuple is the conditions' variables, written out in the
    # render: each ground match charges separately (gringo's bare tuple
    # would silently collapse them all into one charge)
    program = ASPProgram()
    X = Variable("X")
    program.fact(Pick(x=1), Pick(x=2), Pick(x=3))
    program.penalize(Pick(x=X))
    assert ':~ pick(X). [1, "weak-constraint-0", X]' in program.render()
    assert optimal_cost(program) == [3]  # one charge per match


def test_independent_penalties_never_merge_charges() -> None:
    # The auto tuple carries a per-statement discriminator: two penalties
    # over one domain charge separately even when their ground (weight,
    # variables) coincide. Without it, clasp's shared tuple set counted
    # these two charges as one (probed cost was [1]).
    program = ASPProgram()
    X = Variable("X")
    Q = Predicate.define("q_dis", ["x"])
    program.fact(Pick(x=1), Q(x=1))
    program.penalize(Pick(x=X))
    program.penalize(Q(x=X))
    rendered = program.render()
    assert ':~ pick(X). [1, "weak-constraint-0", X]' in rendered
    assert ':~ q_dis(X). [1, "weak-constraint-1", X]' in rendered
    assert optimal_cost(program) == [2]  # one charge each


def test_discriminators_are_program_wide_across_segments() -> None:
    # Ordinals are assigned in document order over the whole program, so
    # penalties in different segments never share a tag
    program = ASPProgram()
    X = Variable("X")
    Q = Predicate.define("q_seg", ["x"])
    extra = program.add_segment("Extra")
    program.fact(Pick(x=1))
    program.penalize(Pick(x=X))
    extra.fact(Q(x=1))
    extra.penalize(Q(x=X))
    rendered = program.render()
    assert '"weak-constraint-0"' in rendered and '"weak-constraint-1"' in rendered
    assert optimal_cost(program) == [2]


def test_explicit_terms_carry_no_discriminator() -> None:
    # terms= means the caller owns tuple identity: rendered exactly as
    # given, so deliberate cross-statement merging stays expressible
    # (test_penalize_is_minimize_in_disguise pins the merging itself)
    program = ASPProgram()
    X = Variable("X")
    program.fact(Pick(x=1))
    program.penalize(Pick(x=X), terms=[X])
    assert "weak-constraint" not in program.render()


def test_discriminator_is_a_program_render_concern() -> None:
    # Like the #show block, the tag exists only in a program's render: a
    # standalone segment renders the bare tuple (a fragment, not a program)
    segment = Segment("Soft")
    X = Variable("X")
    segment.penalize(Pick(x=X))
    assert ":~ pick(X). [1, X]" in segment.render(with_header=False)


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
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)))
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
    program.choose(Choice(Covered(x=1)).add(Covered(x=2)))
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
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)))
    program.fact(Tag(t=1), Tag(t=2))
    program.penalize(Tag(t=T), Count(X, condition=Pick(x=X)) >= 2)
    assert ':~ tag_at(T), #count{ X : pick(X) } >= 2. [1, "weak-constraint-0", T]' in program.render()


def test_bound_type_validated() -> None:
    grounded = build_knapsack().ground()
    with pytest.raises(TypeError, match="bound must be"):
        grounded.optimize(bound="cheap")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="bound must be"):
        grounded.optimize(bound=[1, 0])  # type: ignore[arg-type]  # positional lists are gone
    with pytest.raises(TypeError, match="priority-keyed"):
        grounded.optimize(bound={})
    with pytest.raises(TypeError, match="priority-keyed"):
        grounded.optimize(bound={0: "cheap"})  # type: ignore[dict-item]


def test_raw_optimization_gets_ground_truth_guarding_too() -> None:
    # The observer counts what the text walkers never could: raw
    # optimization gets the same exact tier guard as native directives
    def build_raw() -> ASPProgram:
        program = ASPProgram()
        program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
        program.raw_asp("#minimize{ X,X : pick(X) }.", predicates=[Pick])
        return program

    hinted = build_raw().ground().optimize(bound={0: 1, 2: 0})  # 2 ignored
    assert hinted is not None and [m.cost for m in hinted.path] == [(1,)]
    pruned = build_raw().ground().optimize(bound=1)
    assert pruned is not None and pruned.proven
    assert [m.cost for m in pruned.path] == [(1,)]  # the bound pruned the search
    assert build_raw().ground().optimize(bound=0) is None  # hard ceiling applied


def test_oversized_bound_rejected_with_range() -> None:
    grounded = build_knapsack().ground()
    with pytest.raises(ValueError, match="64-bit cost range"):
        grounded.optimize(bound=2**63)
    with pytest.raises(ValueError, match="64-bit cost range"):
        grounded.optimize(bound={0: -(2**63) - 1})


def test_bound_on_non_optimizing_program_teaches_the_right_lesson() -> None:
    # The optimizing gate fires before bound-arity: the error is about the
    # missing objective, not a confusing zero-tier arity complaint
    program = ASPProgram()
    program.fact(Pick(x=1))
    with pytest.raises(ValueError, match="Nothing to optimize"):
        program.ground().optimize(bound=1)


def test_nested_block_comments_do_not_deadlock() -> None:
    # gringo NESTS block comments; a weak constraint inside a nested block
    # is pure comment — the program does not optimize and solves normally
    program = ASPProgram()
    program.fact(Pick(x=1))
    program.raw_asp("%* outer %* inner *% :~ pick(1). [1] *%")
    result = program.solve()
    assert len(list(result)) == 1  # solvable: no false-positive refusal


def test_penalize_validation_matches_forbid_exactly() -> None:
    # The three parity gaps: aggregate-tuple-shares-global (which could
    # silently DROP the penalty at a relaxed threshold), local singletons,
    # and the anonymous variable in tuple terms
    program = ASPProgram()
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="Aggregate tuple shares"):
        program.penalize(Pick(x=X), Count(X, condition=Pick(x=X)) >= 2, terms=[X])
    Cell2 = Predicate.define("cell_ps", ["x", "y"])
    with pytest.raises(ValueError, match="Singleton variable"):
        program.penalize(
            ConditionalLiteral(Pick(x=X), [Cell2(x=X, y=Y)]),
            Pick(x=1),
            terms=[],
        )
    with pytest.raises(ValueError, match="anonymous variable"):
        program.penalize(Pick(x=X), weight=1, terms=[X, ANY])


def test_vanished_tier_bound_keys_drop_silently() -> None:
    # A declared tier whose elements never hold VANISHES from clasp's
    # levels with no message. Its bound key names nothing, so it drops —
    # a hint that cannot prune, not an error
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(1, X, condition=[Pick(x=X), X > 100], priority=2)  # grounds empty
    program.minimize(X, condition=Pick(x=X), priority=1)
    grounded = program.ground()
    assert grounded.optimization_levels == (1,)  # tier 2 vanished
    dead_key = grounded.optimize(bound={2: 0, 1: 5})  # dead tier 2: ignored
    assert dead_key is not None and dead_key.cost == (1,)
    # Naming only the survivor is the same hint
    informed = grounded.optimize(bound={1: 5})
    assert informed is not None and informed.proven
    assert informed.cost == (1,)
    # A bare int works here: exactly one tier survived
    assert grounded.optimize(bound=5) is not None
    # Without bounds the program is still perfectly optimizable
    result = grounded.optimize()
    assert result is not None and result.proven
    assert result.cost == (1,)  # ONE entry: the cost tuple follows ground levels


def test_fully_empty_objectives_mean_not_optimizing() -> None:
    # Ground truth over declarations: if every objective grounds empty,
    # the program does not optimize — solve() works, optimize() teaches
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=1)).add(Pick(x=2)))
    program.minimize(X, condition=[Pick(x=X), X > 100])  # grounds empty
    grounded = program.ground()
    assert len(list(grounded.solve())) == 4  # not optimizing: enumeration allowed
    with pytest.raises(ValueError, match="Nothing to optimize"):
        grounded.optimize()


def test_observer_catches_every_optimization_spelling() -> None:
    # gringo lowers #maximize (negated weights) and weak constraints into
    # minimize statements before the ASPIF stream, so the ground-truth
    # observer sees all three spellings — raw text included
    for raw in ("#minimize{ X,X : pick(X) }.", "#maximize{ X,X : pick(X) }.", ":~ pick(X). [X@0, X]"):
        program = ASPProgram()
        program.choose(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
        program.raw_asp(raw)
        grounded = program.ground()
        assert grounded.optimization_levels == (0,), raw
        with pytest.raises(ValueError, match=r"optimize\(\)"):
            grounded.solve()
        result = grounded.optimize()
        assert result is not None and result.proven, raw


def test_penalize_weight_rejects_bare_python_type() -> None:
    # A python str slips past the int and String guards and reaches the
    # final structural check: it is neither Value nor Expression
    program = ASPProgram()
    with pytest.raises(TypeError, match="int, Value, or Expression"):
        program.penalize(Pick(x=ANY), weight="cheap")  # type: ignore[arg-type]


def test_penalize_tuple_term_type_validated() -> None:
    # The tuple-term loop rejects a raw python value: only Values,
    # Expressions, or Predicates may sit in the weak-constraint tuple
    program = ASPProgram()
    with pytest.raises(TypeError, match="Values, Expressions, or Predicates"):
        program.penalize(Pick(x=Variable("X")), terms=["bad"])  # type: ignore[list-item]


def test_penalize_condition_must_be_term() -> None:
    # terms=[] skips the auto-tuple branch, so a non-Term condition reaches
    # the per-condition Term check
    program = ASPProgram()
    with pytest.raises(TypeError, match="conditions must be Terms"):
        program.penalize("notaterm", terms=[])  # type: ignore[arg-type]


def test_weak_constraint_priority_getter() -> None:
    # Constructed directly: the library reads .targets/.conditions/.render()
    # but never .priority
    wc = WeakConstraint((Pick(x=Variable("X")),), 1, (Variable("X"),), 3)
    assert wc.priority == 3
    assert wc.targets == (Number(1), Variable("X"))  # weight Number(1), then the tuple term
    assert wc.conditions == [Pick(x=Variable("X"))]


def test_optimization_directive_tuple_term_type_validated() -> None:
    # The directive's tuple-term loop mirrors the weak constraint's: a raw
    # python value is rejected
    program = ASPProgram()
    with pytest.raises(TypeError, match="Values, Expressions, or Predicates"):
        program.minimize(1, "bad", condition=Pick(x=ANY))  # type: ignore[arg-type]


def test_optimization_directive_getters() -> None:
    # Constructed directly: segment.py reads only .element, never
    # .optimization or .priority
    d = OptimizationDirective(Optimization.MINIMIZE, 1, (Variable("X"),), Pick(x=Variable("X")), 2)
    assert d.optimization == Optimization.MINIMIZE
    assert d.priority == 2


def test_anonymous_variable_rejected_in_optimization_tuples() -> None:
    # Same rule as aggregate and weak-constraint tuples: gringo makes _
    # unsafe there, and the tuple defines distinctness
    program = ASPProgram()
    W = Variable("W")
    Weighted = Predicate.define("wtd_anon", ["x", "w"])
    with pytest.raises(ValueError, match="cannot appear in an optimization tuple"):
        program.minimize(W, ANY, condition=Weighted(x=ANY, w=W))
