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
    program.show_when(P, ConditionalLiteral(P(x=X), [P(x=X), Not(Q(x=X))]))
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
        program.show_when(P, ConditionalLiteral(P(x=X), Q(x=Y)))


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
