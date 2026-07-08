"""
Tests for the Segment container: the segments property, add_segment, the
mapping protocol (program["x"] / assignment / del), and the
segment-header rendering rules.
"""

import pytest

from pyclingo import ASPProgram, Choice, Predicate, RangePool, Segment, Variable
from pyclingo.program_elements import Rule

P = Predicate.define("p_seg", ["x"])


def test_segments_property_reflects_insertion_order_and_contents() -> None:
    program = ASPProgram()
    program.fact(P(x=1))  # the default segment alone self-creates on first write
    program.add_segment("grid")
    program["grid"].fact(P(x=2))
    program["grid"].fact(P(x=3))

    segments = program.segments
    assert isinstance(segments, tuple)
    assert [segment.name for segment in segments] == ["Rules", "grid"]
    assert [len(segment) for segment in segments] == [1, 2]
    assert all(isinstance(element, Rule) for segment in segments for element in segment)


def test_add_segment_fixes_position() -> None:
    program = ASPProgram()
    program.add_segment("later")
    program.add_segment("other")
    program["other"].fact(P(x=1))
    program["later"].fact(P(x=2))
    assert [segment.name for segment in program.segments] == ["later", "other"]


def test_writes_require_the_segment_to_exist() -> None:
    # add_segment is the one creation point: program["name"] refuses
    # unknown names instead of quietly creating them (typos stay loud)
    program = ASPProgram()
    with pytest.raises(KeyError, match="Segment 'grid' does not exist"):
        program["grid"].fact(P(x=1))
    program.fact(P(x=1))  # the default segment alone self-creates


def test_getitem_reads_segments_and_never_creates() -> None:
    program = ASPProgram()
    grid = program.add_segment("grid")
    program["grid"].fact(P(x=1))
    assert program["grid"] is grid
    assert len(program["grid"]) == 1
    with pytest.raises(KeyError, match="existing segments: 'grid'"):
        program["typo"]
    with pytest.raises(KeyError, match="'Grid' does not exist"):
        program["Grid"]  # names are exact — no case folding
    assert [segment.name for segment in program.segments] == ["grid"]  # the reads created nothing


def test_add_segment_attaches_a_prebuilt_segment() -> None:
    # A Segment built standalone attaches as-is: the program holds the
    # object it was given, so appends through any handle are visible
    program = ASPProgram()
    grid = Segment("grid")
    returned = program.add_segment(grid)
    assert returned is grid
    assert program["grid"] is grid
    program["grid"].fact(P(x=1))
    assert len(grid) == 1
    assert "p_seg(1)." in program.render()
    with pytest.raises(ValueError, match="Segment 'grid' already exists"):
        program.add_segment(Segment("grid"))
    program.add_segment(Segment("Grid"))  # a different name: case is significant


def test_setitem_assigns_and_replaces_in_place() -> None:
    # Dict-style assignment: a new name appends; an existing name swaps
    # the segment in place, position preserved — the variant-swap workflow
    program = ASPProgram()
    program.fact(P(x=1))
    program["extra"] = Segment("extra")
    program["extra"].fact(P(x=2))
    program.add_segment("tail")
    program["tail"].fact(P(x=3))
    assert [segment.name for segment in program.segments] == ["Rules", "extra", "tail"]

    variant = Segment("extra")
    variant.append(Rule(head=P(x=9)))
    program["extra"] = variant
    assert [segment.name for segment in program.segments] == ["Rules", "extra", "tail"]  # position kept
    assert program["extra"] is variant
    rendered = program.render()
    assert "p_seg(9)." in rendered and "p_seg(2)." not in rendered
    assert rendered.index("p_seg(9).") < rendered.index("p_seg(3).")  # still mid-program

    with pytest.raises(ValueError, match="does not match the segment's name"):
        program["extra"] = Segment("other")
    with pytest.raises(TypeError, match="Expected a Segment"):
        program["extra"] = "not a segment"  # type: ignore[assignment]


def test_segment_names_are_verbatim() -> None:
    assert Segment("GriD").name == "GriD"
    with pytest.raises(ValueError, match="cannot be empty"):
        Segment("   ")
    with pytest.raises(ValueError, match="single-line"):
        Segment("a\nb")


def test_segment_is_a_container_not_a_builder() -> None:
    segment = Segment("grid")
    assert segment.name == "grid"
    assert len(segment) == 0
    assert list(segment) == []


def test_delitem_drops_content() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    program.add_segment("extra")
    program["extra"].fact(P(x=2))
    assert "p_seg(2)." in program.render()
    del program["extra"]
    rendered = program.render()
    assert "p_seg(2)." not in rendered
    assert "p_seg(1)." in rendered
    assert [segment.name for segment in program.segments] == ["Rules"]


def test_delitem_unknown_name_lists_existing() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    program.add_segment("grid")
    program["grid"].fact(P(x=2))
    with pytest.raises(KeyError, match="Segment 'nope' does not exist; existing segments: 'Rules', 'grid'"):
        del program["nope"]


def test_ground_then_delete_segment_gives_ab_comparison() -> None:
    # Each ground() is an independent snapshot, so removing a segment
    # between groundings compares the program with and without it
    program = ASPProgram()
    program.fact(Choice(P(x=RangePool(1, 2))))  # 4 models unconstrained
    program.add_segment("extra")
    program["extra"].forbid(P(x=1))  # 2 models with the constraint
    full = program.ground()
    del program["extra"]
    reduced = program.ground()
    assert len(list(full.solve())) == 2  # unaffected by the removal
    assert len(list(reduced.solve())) == 4


def test_headers_render_only_with_multiple_segments() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    assert "=====" not in program.render()

    program.add_segment("extra")
    program["extra"].fact(P(x=2))
    rendered = program.render()
    # One blank line before the first header, one after every header, two between segments
    assert "\n% ===== Rules =====\n\np_seg(1).\n\n\n% ===== extra =====\n\np_seg(2).\n" in rendered
    assert "\n\n% ===== Rules" in rendered
    assert "\n\n\n% ===== Rules" not in rendered


def test_rejected_rules_append_nothing() -> None:
    # The statement validates before its segment records it, so a rejected
    # closer leaves the segment untouched (and header rendering unflipped)
    program = ASPProgram()
    P = Predicate.define("p_ph", ["x"])
    program.fact(P(x=1))
    program.add_segment("phantom")
    scene = program["phantom"].when(P(x=Variable("Y")))
    with pytest.raises(ValueError, match="Singleton"):
        scene.derive(P(x=2))
    assert [len(seg) for seg in program.segments] == [1, 0]  # nothing was appended
    scene.derive(P(x=Variable("Y")))  # the scene stays open for a corrected closer
    assert "p_ph(Y) :- p_ph(Y)." in program.render()
