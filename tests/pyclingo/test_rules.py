"""
Tests for Rule rendering.
"""

from pyclingo import ASPProgram, ConditionalLiteral, Predicate, Variable
from pyclingo.clingo_handler import LogLevel


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
    program.when([ConditionalLiteral(Q(x=X), Q(x=X)), R()], let=Good())
    assert "q(X) : q(X); r." in program.render()
    # r is deliberately absent, which draws a clingo info; tolerate it
    models = list(program.solve(stop_on_log_level=LogLevel.WARNING))
    assert models[0].atoms(Good) == []
