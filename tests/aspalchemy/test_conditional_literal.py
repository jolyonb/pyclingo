"""Tests for ConditionalLiteral rendering and validation."""

import pytest

from aspalchemy import ASPProgram, ConditionalLiteral, Count, LogLevel, Not, Predicate, Variable


def test_body_literal_after_conditional_literal_stays_separate() -> None:
    # A conditional literal's condition extends through commas, so the
    # separator after it must be a semicolon or the next literal is absorbed.
    # Ground truth: with r absent, "good" must NOT hold.
    program = ASPProgram()
    Q = Predicate.define("q", ["x"])
    R = Predicate.define("r", [], show=False)
    Good = Predicate.define("good", [])
    X = Variable("X")
    program.fact(Q(x=1), Q(x=2))
    program.when(ConditionalLiteral(Q(x=X), Q(x=X)), R()).derive(Good())
    assert "q(X) : q(X); r." in program.render()
    # r is deliberately absent, which draws a clingo info; tolerate it
    models = list(program.solve(stop_on_log_level=LogLevel.WARNING))
    assert models[0].atoms(Good) == []


def test_non_literal_head_rejected() -> None:
    # The head must be a predicate, comparison, or negated term; a bare
    # Variable is none of these and is rejected at construction.
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    with pytest.raises(TypeError, match="head of a conditional literal"):
        ConditionalLiteral(X, Q(x=X))  # type: ignore[arg-type]


def test_is_grounded_delegates_to_element() -> None:
    P = Predicate.define("p", ["x"])
    assert ConditionalLiteral(P(x=1), P(x=1)).is_grounded is True
    X = Variable("X")
    assert ConditionalLiteral(P(x=X), P(x=X)).is_grounded is False


def test_str_matches_render() -> None:
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    cl = ConditionalLiteral(Q(x=X), Q(x=X))
    assert str(cl) == cl.render() == "q(X) : q(X)"


def test_repr_wraps_render() -> None:
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    cl = ConditionalLiteral(Q(x=X), Q(x=X))
    assert repr(cl) == "ConditionalLiteral('q(X) : q(X)')"


def test_conditional_literal_rejected_in_rule_head() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    R = Predicate.define("r", [])
    X = Variable("X")
    with pytest.raises(ValueError, match="cannot be used in rule heads"):
        program.when(R()).derive(ConditionalLiteral(P(x=X), P(x=X)))


def test_collect_variables_delegates_to_element() -> None:
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"])
    X = Variable("X")
    cl = ConditionalLiteral(P(x=X), Q(x=X))
    assert cl.collect_variables() == {"X"}


def test_head_rejection_signposts_disjunction() -> None:
    # The docstring knew disjunctive heads are the unsupported concept; now
    # the error names it and the nearest constructs
    program = ASPProgram()
    P = Predicate.define("p_disj", ["x"])
    Q = Predicate.define("q_disj", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match=r"Choice with at_least\(1\)"):
        program.when(Q(x=X)).derive(ConditionalLiteral(P(x=X), Q(x=X)))


def test_aggregate_bearing_comparison_heads_rejected() -> None:
    # The same category error the condition slot already rejects: gringo
    # answers "#count{...} > 2 : q(Y)" with a bare "unexpected :" parse
    # error, so the head refuses at construction — Not-wrapped included
    P = Predicate.define("p_aggh", ["x"])
    Q = Predicate.define("q_aggh", ["x"])
    X, Y = Variable("X"), Variable("Y")
    aggregate_comparison = Count(X, condition=P(x=X)) > 2
    with pytest.raises(ValueError, match="conditional literal heads"):
        ConditionalLiteral(aggregate_comparison, Q(x=Y))
    with pytest.raises(ValueError, match="conditional literal heads"):
        ConditionalLiteral(Not(aggregate_comparison), Q(x=Y))
