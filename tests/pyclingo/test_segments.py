"""
Tests for the Segment container: the segments property, add_segment/
remove_segment, and the segment-header rendering rules.
"""

import pytest

from pyclingo import ASPProgram, Choice, Predicate, RangePool, Segment
from pyclingo.program_elements import Rule

P = Predicate.define("p_seg", ["x"])


def test_segments_property_reflects_insertion_order_and_contents() -> None:
    program = ASPProgram()
    program.fact(P(x=1))  # creates the default segment on first write
    program.fact(P(x=2), segment="grid")
    program.fact(P(x=3), segment="grid")

    segments = program.segments
    assert isinstance(segments, tuple)
    assert [segment.name for segment in segments] == ["rules", "grid"]
    assert [len(segment) for segment in segments] == [1, 2]
    assert all(isinstance(element, Rule) for segment in segments for element in segment)


def test_add_segment_fixes_position() -> None:
    program = ASPProgram()
    program.add_segment("later")
    program.fact(P(x=1), segment="other")
    program.fact(P(x=2), segment="later")
    assert [segment.name for segment in program.segments] == ["later", "other"]


def test_segment_is_a_container_not_a_builder() -> None:
    segment = Segment("grid")
    assert segment.name == "grid"
    assert len(segment) == 0
    assert list(segment) == []


def test_remove_segment_drops_content() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    program.fact(P(x=2), segment="extra")
    assert "p_seg(2)." in program.render()
    program.remove_segment("extra")
    rendered = program.render()
    assert "p_seg(2)." not in rendered
    assert "p_seg(1)." in rendered
    assert [segment.name for segment in program.segments] == ["rules"]


def test_remove_segment_unknown_name_lists_existing() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    program.fact(P(x=2), segment="grid")
    with pytest.raises(ValueError, match="Segment 'nope' does not exist; existing segments: 'rules', 'grid'"):
        program.remove_segment("nope")


def test_ground_then_remove_segment_gives_ab_comparison() -> None:
    # Each ground() is an independent snapshot, so removing a segment
    # between groundings compares the program with and without it
    program = ASPProgram()
    program.fact(Choice(P(x=RangePool(1, 2))))  # 4 models unconstrained
    program.forbid(P(x=1), segment="extra")  # 2 models with the constraint
    full = program.ground()
    program.remove_segment("extra")
    reduced = program.ground()
    assert len(list(full.solve())) == 2  # unaffected by the removal
    assert len(list(reduced.solve())) == 4


def test_headers_render_only_with_multiple_segments() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    assert "=====" not in program.render()

    program.fact(P(x=2), segment="extra")
    rendered = program.render()
    # One blank line before the first header, two between segments
    assert "\n% ===== Rules =====\np_seg(1).\n\n\n% ===== Extra =====\np_seg(2).\n" in rendered
    assert "\n\n% ===== Rules" in rendered
    assert "\n\n\n% ===== Rules" not in rendered
