"""
Tests for #show directive emission and visibility overrides.
"""

import pytest

from pyclingo import ASPProgram, ConditionalLiteral, Count, Not, Predicate, Variable


def test_hiding_everything_emits_bare_show() -> None:
    # Without the bare "#show.", clingo defaults to showing every atom
    program = ASPProgram()
    P = Predicate.define("secret", ["x"])
    program.fact(P(x=1))
    program.hide(P)
    assert "#show." in program.render()
    assert next(iter(program.solve())).atoms() == []


def test_define_time_hidden_also_emits_bare_show() -> None:
    program = ASPProgram()
    P = Predicate.define("plumbing", ["x"], show=False)
    program.fact(P(x=1))
    assert "#show." in program.render()


def test_show_when_predicates_reach_the_round_trip() -> None:
    # A predicate appearing ONLY in a show_when condition must still be known
    # to the solution converter
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    program.fact(P(x=1), Q(x=1))
    program.hide(Q)
    program.show_when(ConditionalLiteral(P(x=X), [P(x=X), Not(Q(x=X))]))
    assert "#show p(X) : p(X), not q(X)." in program.render()
    list(program.solve())  # must not raise "Unknown predicate type"


def test_aggregates_rejected_in_conditional_literal_conditions() -> None:
    # clingo's grammar rejects aggregates inside CL conditions — caught at
    # construction (this also means nothing mutable can reach a show directive)
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    count = Count(Y, condition=P(x=Y))
    with pytest.raises(ValueError, match="conditional literal conditions"):
        ConditionalLiteral(P(x=X), [P(x=X), count == 1])


def test_show_when_validates_its_condition() -> None:
    # A #show directive has no rule body: every variable must be bound inside
    # the conditional literal itself
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"])
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="Unsafe"):
        program.show_when(ConditionalLiteral(P(x=X), Q(x=Y)))


def test_show_of_underived_predicate_raises_at_render() -> None:
    # No raw_asp blocks: an uncollected show target is provably absent
    program = ASPProgram()
    P = Predicate.define("p_shown", ["x"])
    Ghost = Predicate.define("ghost", ["x"])
    program.fact(P(x=1))
    program.show(Ghost)
    with pytest.raises(ValueError, match="nothing derives it"):
        program.render()


def test_show_with_raw_asp_present_is_not_validated() -> None:
    # Raw text is invisible to walkers; the override must still emit
    program = ASPProgram()
    Q = Predicate.define("q_raw", ["x"])
    program.raw_asp("q_raw(1).")
    program.show(Q)
    assert "#show q_raw/1." in program.render()


def test_show_of_negated_only_predicate_emits_no_positive_directive() -> None:
    # An explicit show() of a predicate occurring only as -p must not emit a
    # dangling "#show p/n." (gringo infos on absent signatures)
    program = ASPProgram()
    P = Predicate.define("p_negonly", ["x"], show=False)
    program.fact(-P(x=1))
    program.show(P)
    rendered = program.render()
    assert "#show -p_negonly/1." in rendered
    assert "#show p_negonly/1." not in rendered
    model = next(iter(program.solve()))
    assert [a.negated for a in model.atoms(P)] == [True]


def test_show_when_head_must_be_a_predicate() -> None:
    # The shown predicate is the head; a comparison head has nothing to show
    program = ASPProgram()
    Q = Predicate.define("q_key", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match="head is a predicate atom"):
        program.show_when(ConditionalLiteral(X == 1, Q(x=X)))


def test_show_when_covers_its_sign_only() -> None:
    # A positive-head conditional governs positive atoms; the negated atoms
    # fall back to their sign's default (here: shown via the signature form)
    program = ASPProgram()
    P = Predicate.define("p_mix", ["x"])
    D = Predicate.define("d_mix", ["x"], show=False)
    X = Variable("X")
    program.fact(P(x=1), P(x=3), -P(x=2), D(x=1))
    program.show_when(ConditionalLiteral(P(x=X), [P(x=X), D(x=X)]))
    rendered = program.render()
    assert "#show p_mix(X) : p_mix(X), d_mix(X)." in rendered
    assert "#show -p_mix/1." in rendered
    assert "#show p_mix/1." not in rendered  # positive sign is conditional now
    model = next(iter(program.solve()))
    shown = sorted(str(a) for a in model.atoms())
    assert shown == ["-p_mix(2)", "p_mix(1)"]  # p_mix(3) filtered by the condition


def test_show_when_both_signs_independently() -> None:
    # Sign-specific conditionals coexist: each governs its own atoms (probed)
    program = ASPProgram()
    P = Predicate.define("p_both", ["x"])
    D = Predicate.define("d_both", ["x"], show=False)
    X = Variable("X")
    program.fact(P(x=1), P(x=3), -P(x=2), -P(x=4), D(x=1), D(x=2))
    program.show_when(ConditionalLiteral(P(x=X), [P(x=X), D(x=X)]))
    program.show_when(ConditionalLiteral(-P(x=X), [-P(x=X), D(x=X)]))
    model = next(iter(program.solve()))
    shown = sorted(str(a) for a in model.atoms())
    assert shown == ["-p_both(2)", "p_both(1)"]


def test_show_when_on_underived_predicate_rejected_at_render() -> None:
    program = ASPProgram()
    P = Predicate.define("p_und", ["x"])
    Ghost = Predicate.define("ghost_sw", ["x"])
    X = Variable("X")
    program.fact(P(x=1))
    program.show_when(ConditionalLiteral(Ghost(x=X), Ghost(x=X)))
    with pytest.raises(ValueError, match="nothing derives them"):
        program.render()


def test_aggregate_tuple_terms_are_data_not_atoms() -> None:
    # A predicate used only as an aggregate tuple term must not emit a
    # dangling #show (it is data, demoted like any argument position)
    Island = Predicate.define("island_agg", ["loc"])
    Q = Predicate.define("q_agg", ["x"], show=False)
    Total = Predicate.define("total_agg", ["n"])
    program = ASPProgram()
    N, Y = Variable("N"), Variable("Y")
    program.fact(Q(x=1), Q(x=2))
    program.when(N == Count(Island(loc=Y), condition=Q(x=Y))).derive(Total(n=N))
    rendered = program.render()
    assert "#show island_agg/1." not in rendered
    model = next(iter(program.solve()))
    assert [a["n"].value for a in model.atoms(Total)] == [2]


def test_show_when_condition_cannot_self_vouch_a_directive() -> None:
    # Emission uses the same derivation evidence as validation: a class
    # mentioned only inside a show_when condition no longer vouches its
    # own dangling signature directive into the render (the conditional
    # itself still fails loud at ground via gringo's underived-atom info)
    P = Predicate.define("p_sv", ["x"])
    Ghost = Predicate.define("ghost_sv", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(P(x=1))
    program.show_when(ConditionalLiteral(P(x=X), [P(x=X), Ghost(x=X)]))
    assert "#show ghost_sv/1." not in program.render()  # no self-vouched directive
    with pytest.raises(RuntimeError, match="ghost_sv"):
        program.solve()  # the underived condition atom halts at ground, loudly
