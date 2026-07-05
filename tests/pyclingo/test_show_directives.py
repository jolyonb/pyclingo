"""
Tests for #show directive emission and visibility overrides.
"""

from pyclingo import ASPProgram, Not, Predicate, Variable
from pyclingo.conditional_literal import ConditionalLiteral


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
