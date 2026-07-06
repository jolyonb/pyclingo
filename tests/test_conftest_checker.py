"""
Tests for the suite-wide render conformance checker itself.
"""

import pytest

from pyclingo import ASPProgram
from tests.conftest import assert_clingo_accepts


def test_checker_accepts_valid_programs() -> None:
    assert_clingo_accepts("p(1..3). q(X) :- p(X), not X < 2.")


def test_checker_rejects_invalid_programs() -> None:
    with pytest.raises(pytest.fail.Exception, match="not valid clingo"):
        assert_clingo_accepts("q(X) :- p(X), not (X < 2).")


def test_checker_is_active_by_default() -> None:
    assert ASPProgram.render.__name__ == "checked_render"


@pytest.mark.allow_invalid_render
def test_marker_opts_out_of_the_checker() -> None:
    assert ASPProgram.render.__name__ == "render"
