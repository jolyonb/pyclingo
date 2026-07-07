"""
Tests for Comment: single-line renders after %, multi-line as a %* *% block.
gringo NESTS block comments, so both delimiters are forbidden in multi-line
text; single-line text is unrestricted (nothing after % is parsed).
"""

import pytest

from pyclingo import ASPProgram, Predicate
from pyclingo.program_elements import Comment


def test_single_line_renders_as_line_comment() -> None:
    assert Comment("a note").render() == "% a note"


def test_multi_line_renders_as_block() -> None:
    assert Comment("one\ntwo").render() == "%*\none\ntwo\n*%"


def test_single_line_may_contain_block_delimiters() -> None:
    # After % nothing is parsed, so *% and %* are harmless
    assert Comment("mentions *% and %* freely").render() == "% mentions *% and %* freely"


def test_multi_line_rejects_both_delimiters() -> None:
    with pytest.raises(ValueError, match="block comment delimiters"):
        Comment("mentions a %* marker\nsecond line")
    with pytest.raises(ValueError, match="block comment delimiters"):
        Comment("mentions a *% marker\nsecond line")


def test_comments_round_trip_through_a_program() -> None:
    # The autouse conformance fixture parse-checks this render
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    program.comment("single line with *% inside")
    program.comment("block\ncomment")
    program.fact(P(x=1))
    rendered = program.render()
    assert "% single line" in rendered
    assert "%*\nblock\ncomment\n*%" in rendered
