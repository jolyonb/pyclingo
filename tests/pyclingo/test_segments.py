"""
Tests for the Segment container: the segments property, add_segment, the
mapping protocol (program["x"] / assignment / del), the segment-header
rendering rules, and how segments stamp elements with source locations.
"""

import inspect
import re

import pytest

from pyclingo import ASPProgram, Choice, Predicate, RangePool, Segment, SourceLocation, Variable
from pyclingo.program_elements import BlankLine, Comment, Rule

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


def test_mapping_protocol_over_segment_names() -> None:
    # dict convention: membership, iteration, and len speak segment NAMES
    # in rendering order; .segments serves the objects
    program = ASPProgram()
    assert len(program) == 0
    assert "Rules" not in program  # the default segment does not exist until first write
    program.fact(P(x=1))
    program.add_segment("grid")
    assert "Rules" in program
    assert "grid" in program
    assert "typo" not in program
    assert list(program) == ["Rules", "grid"]
    assert len(program) == 2


def test_membership_is_by_name_not_object() -> None:
    program = ASPProgram()
    grid = program.add_segment("grid")
    with pytest.raises(TypeError, match=r"Membership is by name.*'grid' in program"):
        grid in program  # type: ignore[operator]  # noqa: B015 (the membership test is the act under test)
    with pytest.raises(TypeError, match=r"by name \(a string\), got int"):
        3 in program  # type: ignore[operator]  # noqa: B015


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


def test_setitem_replaces_in_place_and_never_creates() -> None:
    # Assignment REPLACES an existing segment, position preserved — the
    # variant-swap workflow. Creation stays add_segment's job: a typo'd
    # replacement must not silently append a segment at the program's end
    program = ASPProgram()
    program.fact(P(x=1))
    with pytest.raises(KeyError, match=r"assignment only replaces.*add_segment"):
        program["extra"] = Segment("extra")
    program.add_segment("extra")
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
    program.choose(Choice(P(x=RangePool(1, 2))))  # 4 models unconstrained
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


def test_segment_names_are_exact() -> None:
    # A segment's name is taken verbatim — no case folding, no munging.
    # Exact duplicates error; different casings are different segments.
    program = ASPProgram()
    program.add_segment("Symbols")

    with pytest.raises(ValueError, match="Segment 'Symbols' already exists"):
        program.add_segment("Symbols")

    program.add_segment("symbols")  # a distinct segment
    assert [segment.name for segment in program.segments] == ["Symbols", "symbols"]


def test_writes_address_segments_by_exact_name() -> None:
    program = ASPProgram()
    TestPred = Predicate.define("test", ["value"])
    program.add_segment("Symbols")
    program["Symbols"].fact(TestPred(value=1))

    # A different casing is a different (nonexistent) segment
    with pytest.raises(KeyError, match="Segment 'SYMBOLS' does not exist"):
        program["SYMBOLS"].fact(TestPred(value=2))

    assert "test(1)." in program.render()


def test_default_segment_name_is_verbatim() -> None:
    program = ASPProgram(default_segment="MyRules")
    TestPred = Predicate.define("test", ["value"])
    program.fact(TestPred(value=1))  # the default segment self-creates

    with pytest.raises(ValueError, match="Segment 'MyRules' already exists"):
        program.add_segment("MyRules")
    with pytest.raises(KeyError, match="'myrules' does not exist"):
        program["myrules"]


def test_multiline_segment_name_rejected() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="single-line"):
        program.add_segment("a\nb")


def test_empty_segment_names_rejected_everywhere() -> None:
    program = ASPProgram()
    P = Predicate.define("p_seg", ["x"])
    with pytest.raises(ValueError, match="cannot be empty"):
        program.add_segment("")
    with pytest.raises(ValueError, match="cannot be empty"):
        program["  "].fact(P(x=1))


def test_segment_headers_render_the_name_verbatim() -> None:
    program = ASPProgram()
    P = Predicate.define("p_seg2", ["x"])
    program.add_segment("grid_stuff")
    program["grid_stuff"].fact(P(x=1))
    program.fact(P(x=2))  # second segment so headers render
    assert "% ===== grid_stuff =====" in program.render()


def test_validate_name_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="Segment name must be a string, got int"):
        Segment(123)  # type: ignore[arg-type]


def test_flat_forbid_rejects_non_term_condition() -> None:
    program = ASPProgram()
    with pytest.raises(TypeError, match=r"forbid\(\) conditions must be Terms, got str"):
        program.forbid("p(X)")  # type: ignore[arg-type]


def test_blank_line_and_section_append_elements() -> None:
    seg = Segment("s")
    seg.blank_line()
    assert len(seg) == 1
    assert isinstance(next(iter(seg)), BlankLine)

    seg.section("Clues")
    assert len(seg) == 3  # the blank line, then section's own blank + comment
    elements = list(seg)
    assert isinstance(elements[1], BlankLine)
    assert isinstance(elements[2], Comment)
    assert "% Clues" in seg.render(with_header=False)


def test_section_on_fresh_segment_adds_blank_and_title() -> None:
    seg = Segment("s")
    seg.section("Clues")
    assert len(seg) == 2
    assert "% Clues" in seg.render(with_header=False)


def test_render_with_header_absorbs_the_sections_leading_blank() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    program.add_segment("x")
    program["x"].section("T")
    program["x"].fact(P(x=2))
    rendered = program.render()
    assert "% ===== x =====\n\n% T" in rendered
    assert "% ===== x =====\n\n\n" not in rendered  # the section's own blank absorbed, not doubled


def test_check_pending_raises_for_unclosed_when() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    program.when(P(x=Variable("X")))  # opened, never closed
    with pytest.raises(ValueError, match=r"incomplete when\(\) statements: when\(p_seg\(X\)\)"):
        program.render()


def test_when_completing_twice_raises() -> None:
    program = ASPProgram()
    X = Variable("X")
    w = program.when(P(x=X))
    w.derive(P(x=X))
    with pytest.raises(RuntimeError, match=r"already completed with \.derive\(\)"):
        w.derive(P(x=X))


def test_when_derive_rejects_non_term_head() -> None:
    program = ASPProgram()
    with pytest.raises(TypeError, match=r"derive\(\) head must be a Term, got str"):
        program.when(P(x=1)).derive("p(2)")  # type: ignore[arg-type]


def test_when_forbid_rejects_empty_violation() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match=r"at least one violation term"):
        program.when(P(x=1)).forbid()


def test_when_forbid_happy_path_and_non_term_violation() -> None:
    program = ASPProgram()
    A = Predicate.define("a", ["x"])
    B = Predicate.define("b", ["x"])
    X = Variable("X")
    program.when(A(x=X)).forbid(B(x=X))
    assert ":- a(X), b(X)." in program.render()

    program2 = ASPProgram()
    with pytest.raises(TypeError, match=r"forbid\(\) violation terms must be Terms, got str"):
        program2.when(A(x=1)).forbid("b")  # type: ignore[arg-type]


def test_when_penalize_rejects_empty_violation() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match=r"at least one violation term"):
        program.when(P(x=1)).penalize()


def test_when_penalize_happy_path_and_non_term_violation() -> None:
    program = ASPProgram()
    A = Predicate.define("a", ["x"])
    B = Predicate.define("b", ["x"])
    X = Variable("X")
    program.when(A(x=X)).penalize(B(x=X))
    rendered = program.render()
    assert ':~ a(X), b(X). [1, "weak-constraint-0", X]' in rendered

    program2 = ASPProgram()
    with pytest.raises(TypeError, match=r"penalize\(\) violation terms must be Terms, got str"):
        program2.when(A(x=1)).penalize("b")  # type: ignore[arg-type]


def test_dangling_when_reports_its_open_site() -> None:
    program = ASPProgram()
    program.fact(P(x=1))
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    program.when(P(x=Variable("X")))  # the very next line -> lineno + 1
    opened_at = SourceLocation(__file__, lineno + 1).display()
    with pytest.raises(ValueError, match=re.escape(f"when(p_seg(X)) opened at {opened_at}")):
        program.segments[0].check_pending()
    with pytest.raises(ValueError, match=re.escape(f"when(p_seg(X)) opened at {opened_at}")):
        program.render()


def test_when_location_is_the_open_site() -> None:
    program = ASPProgram()
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    w = program.when(P(x=Variable("X")))  # the very next line -> lineno + 1
    assert w.location == SourceLocation(__file__, lineno + 1)
    w.derive(P(x=Variable("X")))


def test_when_location_is_none_with_capture_off() -> None:
    program = ASPProgram(source_locations=False)
    program.fact(P(x=1))
    w = program.when(P(x=Variable("X")))
    assert w.location is None
    with pytest.raises(ValueError, match=r"incomplete when\(\) statements: when\(p_seg\(X\)\)") as excinfo:
        program.render()
    assert "opened at" not in str(excinfo.value)


def test_one_line_when_chain_stamps_the_when_line_alone() -> None:
    program = ASPProgram()
    X = Variable("X")
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    program.when(P(x=X)).derive(P(x=X))  # opened and closed on lineno + 1
    element = list(program.segments[0])[-1]
    assert element.source_location == SourceLocation(__file__, lineno + 1)
    assert element.closed_at is None


def test_split_when_records_both_open_and_close_sites() -> None:
    program = ASPProgram()
    X = Variable("X")
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    w = program.when(P(x=X))  # opened on lineno + 1
    w.derive(P(x=X))  # closed on lineno + 2
    element = list(program.segments[0])[-1]
    assert element.source_location == SourceLocation(__file__, lineno + 1)
    assert element.closed_at == SourceLocation(__file__, lineno + 2)


def test_segment_capture_off_leaves_elements_unstamped() -> None:
    segment = Segment("quiet", source_locations=False)
    segment.fact(P(x=1))
    element = list(segment)[-1]
    assert element.source_location is None
    assert element.closed_at is None


def test_attached_segment_keeps_its_own_capture_setting() -> None:
    # A prebuilt segment attaches with the capture setting it was built
    # with; only segments the program itself creates inherit the program's
    program = ASPProgram(source_locations=False)
    program.fact(P(x=1))  # the default segment inherits capture-off
    assert list(program.segments[0])[-1].source_location is None

    program.add_segment("inherited")  # program-created: inherits capture-off
    program["inherited"].fact(P(x=2))
    assert list(program["inherited"])[-1].source_location is None

    own = Segment("own")  # capture on by default, kept through attachment
    program.add_segment(own)
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    own.fact(P(x=3))  # the very next line -> lineno + 1
    assert list(own)[-1].source_location == SourceLocation(__file__, lineno + 1)

    capturing_program = ASPProgram()
    silent = Segment("silent", source_locations=False)
    capturing_program.add_segment(silent)
    silent.fact(P(x=4))
    assert list(silent)[-1].source_location is None


def test_append_keeps_an_already_set_source_location() -> None:
    segment = Segment("s")
    rule = Rule(head=P(x=1))
    preset = SourceLocation("elsewhere.py", 7)
    rule.source_location = preset
    segment.append(rule)
    assert rule.source_location is preset


def test_append_rejects_non_elements_with_teaching() -> None:
    # A bare string died three stages later with a raw AttributeError
    segment = Segment("Guard")
    with pytest.raises(TypeError, match=r"for verbatim ASP text use raw_asp\(\)"):
        segment.append("q(2).")  # type: ignore[arg-type]


def test_bool_conditions_teach_the_predicate_equality_trap() -> None:
    # cell_a == cell_b between two instances is Python value equality, and
    # the resulting bool used to draw only "must be Terms, got bool"
    program = ASPProgram()
    Cell = Predicate.define("cell_eqtrap", ["x"])
    with pytest.raises(TypeError, match="Bind one side to a Variable"):
        program.when(Cell(x=1) == Cell(x=2)).derive(Cell(x=3))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Bind one side to a Variable"):
        program.forbid(Cell(x=1) == Cell(x=1))  # type: ignore[arg-type]
