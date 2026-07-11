"""
Tests for Comment: single-line renders after %, multi-line as a %* *% block.
gringo NESTS block comments, so both delimiters are forbidden in multi-line
text; single-line text is unrestricted (nothing after % is parsed).
"""

import clingo
import pytest

from aspalchemy import ASPProgram, Predicate
from aspalchemy.program_elements import Comment


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


def test_nul_rejected_in_comment_text() -> None:
    with pytest.raises(ValueError, match=r"NUL.*silently truncates"):
        Comment("note\x00")


def test_clingo_truncates_at_nul_receipt() -> None:
    # The hazard every NUL check exists for: Control.add drops everything
    # after the first NUL byte with zero diagnostics. If this receipt ever
    # fails, clingo has started rejecting NUL and the checks can come out.
    messages: list[str] = []
    control = clingo.Control(logger=lambda code, message: messages.append(message))
    control.add("base", [], "a.\x00 b.")
    control.ground([("base", [])])
    atoms = [str(atom.symbol) for atom in control.symbolic_atoms]
    assert atoms == ["a"]  # b. silently gone
    assert messages == []  # and clingo said nothing
