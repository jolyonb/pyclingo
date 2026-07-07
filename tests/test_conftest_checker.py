"""
Tests for the suite-wide render conformance checker itself.
"""

import pytest

from pyclingo import ASPProgram, Count, Predicate, Variable
from tests.conftest import assert_clingo_accepts


def test_checker_accepts_valid_programs() -> None:
    assert_clingo_accepts("p(1..3). q(X) :- p(X), not X < 2.")


def test_checker_rejects_invalid_programs() -> None:
    with pytest.raises(pytest.fail.Exception, match="not valid clingo"):
        assert_clingo_accepts("q(X) :- p(X), not (X < 2).")


def test_checker_is_active_by_default() -> None:
    assert ASPProgram.render.__name__ == "checked_program_render"


@pytest.mark.allow_invalid_render
def test_marker_opts_out_of_the_checker() -> None:
    assert ASPProgram.render.__name__ == "render"


def test_top_level_term_renders_are_wrapped_and_checked() -> None:
    # The patched render parse-checks direct term assertions; valid terms pass
    X = Variable("X")
    P = Predicate.define("p", ["x"])
    assert (~(X < 5)).render() == "not X < 5"
    assert Count(X, condition=P(x=X)).render() == "#count{ X : p(X) }"


def test_nested_renders_do_not_multiply_checks() -> None:
    # A full program render recurses through term renders; only the outermost
    # parse fires (this is a smoke test that nothing raises and output is sane)
    P = Predicate.define("p", ["x"])
    program = ASPProgram()
    program.fact(P(x=1))
    assert "p(1)." in program.render()
