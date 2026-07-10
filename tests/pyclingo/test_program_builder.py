"""
Tests for ASPProgram's construction methods: fact, when, forbid,
raw_asp, define_constant, the guards on their inputs, and the
annotated / line-paired render paths.
"""

import copy
import inspect

import pytest

from pyclingo import (
    ASPProgram,
    Choice,
    ConditionalLiteral,
    Count,
    DefinedConstant,
    GroundingError,
    Number,
    Predicate,
    PyClingoBaseException,
    RangePool,
    SourceLocation,
    Variable,
)
from pyclingo.program_elements import BlankLine, Comment, RawASP, Rule
from pyclingo.segment import Segment


def _here() -> SourceLocation:
    """The caller's own file and line, for building expected locations."""
    frame = inspect.currentframe()
    assert frame is not None and frame.f_back is not None
    return SourceLocation(frame.f_back.f_code.co_filename, frame.f_back.f_lineno)


def test_facts_must_be_grounded() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match=r"grounded.*variable\(s\) X"):
        program.fact(P(x=Variable("X")))


def test_builder_methods_reject_wrong_types() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="must be Predicate instances, got str"):
        program.fact("p(1).")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be Terms, got str"):
        program.when("p(X)").derive(P(x=1))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="raw_asp\\(\\) text must be a string"):
        program.raw_asp(42)  # type: ignore[arg-type]


def test_empty_conditions_are_rejected() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="forbid\\(\\) requires at least one"):
        program.forbid()
    with pytest.raises(ValueError, match="use fact\\(\\) or require\\(\\)"):
        program.when()


def test_choose_states_bare_choice_rules() -> None:
    # A bare choice rule is an unconditional statement with nothing
    # asserted; choose() states it, and a conditioned choice stays
    # when(...).derive(choice)
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    program.choose(Choice(P(x=RangePool(1, 3))))
    assert "{ p(1..3) }." in program.render()


def test_fact_refuses_a_choice_and_names_the_verb() -> None:
    # fact() asserts; a choice asserts nothing, so the error teaches choose()
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match=r"choice rule \(\{ p\(1\.\.3\) \}\) is not a fact.*choose\(\)"):
        program.fact(Choice(P(x=RangePool(1, 3))))  # type: ignore[arg-type]


def test_choose_refuses_atoms_and_other_types() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match=r"got the atom p\(1\).*fact\(p\(1\)\)"):
        program.choose(P(x=1))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"choose\(\) takes a Choice, got str"):
        program.choose("{ p(1..3) }.")  # type: ignore[arg-type]


def test_constant_values_must_fit_clingo_integers() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="outside clingo's integer range"):
        program.define_constant("big", 2**40)


def test_aggregate_comparisons_cannot_be_heads() -> None:
    # clingo rejects these with a misleading "unsafe variables" error
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match="cannot be rule heads"):
        program.when(P(x=1)).derive(Count(X, condition=P(x=X)) == 1)


def test_pool_comparisons_cannot_be_heads() -> None:
    # Head pools expand conjunctively: X = (1; 2) forces X to equal BOTH
    # elements — false for every X, silently unsatisfiable
    program = ASPProgram()
    P = Predicate.define("p_ph", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match=r"silently\s+unsatisfiable.*in the body"):
        program.when(P(x=X)).derive(X.in_((1, 2)))


def test_const_nullary_predicate_collision_rejected() -> None:
    # gringo substitutes a #const into every occurrence of a same-named atom
    program = ASPProgram()
    program.define_constant("north", 5)
    North = Predicate.define("north", [], show=False)
    Dir = Predicate.define("dir", ["d"])
    program.fact(Dir(d=North()))
    with pytest.raises(ValueError, match="both a #const and a nullary predicate"):
        program.render()


def test_multiline_header_rejected() -> None:
    with pytest.raises(ValueError, match="single line"):
        ASPProgram(header="a\nb")


def test_not_reserved_as_constant_name() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="reserved"):
        program.define_constant("not", 1)


def test_define_constant_rejects_bool_and_non_ascii() -> None:
    program = ASPProgram()
    with pytest.raises(TypeError, match="got bool"):
        program.define_constant("flag", True)
    with pytest.raises(ValueError, match="ASCII"):
        program.define_constant("größe", 3)


def test_empty_fact_rejected() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="at least one statement"):
        program.fact()


def test_empty_conditional_literal_condition_rejected() -> None:
    # A conditionless CL renders as a plain (binding) literal — a category
    # error caught at construction; None must not slip past the empty-list wall
    P = Predicate.define("p_cl", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match="at least one condition"):
        ConditionalLiteral(P(x=X), [])
    with pytest.raises(ValueError, match="at least one condition"):
        ConditionalLiteral(P(x=X), None)  # type: ignore[arg-type]


def test_failed_rule_leaves_builders_unfrozen() -> None:
    # A rejected rule never existed; the builder must remain repairable
    program = ASPProgram()
    P = Predicate.define("p_uf", ["x"])
    Q = Predicate.define("q_uf", ["x"])
    X, Y = Variable("X"), Variable("Y")
    choice = Choice(P(x=X), condition=Q(x=X))
    scene = program.when(Q(x=Y))
    with pytest.raises(ValueError, match="Singleton variable"):
        scene.derive(choice)  # Y is a singleton — rule rejected
    scene.derive(P(x=Y))  # close the scene so the program stays renderable
    choice.add(P(x=X + 1), Q(x=X))  # still mutable: the rule never captured it
    program.choose(choice)
    assert "{ p_uf(X) : q_uf(X); p_uf(X + 1) : q_uf(X) }" in program.render()


def test_blank_line_opens_a_gap_in_the_default_segment() -> None:
    program = ASPProgram()
    P = Predicate.define("p_bl", ["x"])
    program.fact(P(x=1))
    program.blank_line()
    program.fact(P(x=2))
    assert "p_bl(1).\n\np_bl(2)." in program.render()


def test_section_adds_a_title_comment_to_the_default_segment() -> None:
    program = ASPProgram()
    P = Predicate.define("p_sec", ["x"])
    program.section("My Rules")
    program.fact(P(x=1))
    assert "% My Rules" in program.render()


def test_define_constant_rejects_non_string_name() -> None:
    program = ASPProgram()
    with pytest.raises(TypeError, match="must be a string"):
        program.define_constant(5, 1)  # type: ignore[arg-type]


def test_define_constant_rejects_non_lowercase_start() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="start with a lowercase letter"):
        program.define_constant("Big", 1)


def test_define_constant_rejects_punctuation_in_name() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="letters, digits, and underscores"):
        program.define_constant("a-b", 1)


def test_define_constant_rejects_duplicate_registration() -> None:
    program = ASPProgram()
    program.define_constant("n", 4)
    with pytest.raises(ValueError, match="already registered"):
        program.define_constant("n", 5)


def test_define_constant_rejects_unsafe_string_value() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="quotes, backslashes, newlines, or NUL"):
        program.define_constant("greet", 'he"llo')


def test_show_when_rejects_non_conditional_literal() -> None:
    program = ASPProgram()
    P = Predicate.define("p_sw", ["x"])
    with pytest.raises(TypeError, match="must be a ConditionalLiteral"):
        program.show_when(P(x=1))  # type: ignore[arg-type]


def test_render_emits_the_header_comment() -> None:
    program = ASPProgram(header="My Puzzle")
    P = Predicate.define("p_hdr", ["x"])
    program.fact(P(x=1))
    assert "% My Puzzle" in program.render()


def test_render_quotes_a_string_valued_constant() -> None:
    program = ASPProgram()
    P = Predicate.define("p_str", ["x"])
    program.fact(P(x=1))
    program.define_constant("greeting", "hello")
    assert '#const greeting = "hello".' in program.render()


def test_render_skips_an_empty_segment() -> None:
    program = ASPProgram()
    P = Predicate.define("p_es", ["x"])
    program.fact(P(x=1))
    program.add_segment("empty")  # never gets a statement
    assert "empty" not in program.render()


def test_render_rejects_an_undeclared_defined_constant() -> None:
    program = ASPProgram()
    P = Predicate.define("p_uc", ["x"])
    program.fact(P(x=DefinedConstant("undeclared")))
    with pytest.raises(ValueError, match="Undefined constants used in program"):
        program.render()


@pytest.mark.allow_invalid_render
def test_ground_wraps_a_clingo_parse_error() -> None:
    program = ASPProgram()
    program.raw_asp("p(1) :-")  # incomplete rule: gringo fails to parse it
    with pytest.raises(GroundingError, match="parsing"):
        program.ground()


def test_grounding_error_roots_at_the_family_base() -> None:
    # GroundingError is pyclingo's own class, rooted at the family base —
    # deliberately NOT a RuntimeError (pre-publication, there is no old
    # handler to keep working)
    assert issubclass(GroundingError, PyClingoBaseException)
    assert not issubclass(GroundingError, RuntimeError)
    program = ASPProgram()
    program.raw_asp("p_ge(1")  # unterminated: a parse error
    with pytest.raises(PyClingoBaseException):
        program.ground()


def test_ground_wraps_a_grounding_error() -> None:
    program = ASPProgram()
    program.raw_asp("p(X) :- q(Y).")  # X unbound in the head — unsafe at ground time
    with pytest.raises(GroundingError, match="Grounding failed"):
        program.ground()


def test_optimize_rejects_negative_max_iterations() -> None:
    program = ASPProgram()
    P = Predicate.define("p_opt", ["x"])
    program.fact(P(x=1))
    program.penalize(P(x=1))
    with pytest.raises(ValueError, match="non-negative"):
        program.optimize(max_iterations=-1)


def test_rule_collect_predicates_returns_the_classes() -> None:
    P = Predicate.define("p_cp", ["x"])
    rule = Rule(head=P(x=1))
    assert rule.collect_predicates() == {P}


def test_comment_rejects_non_string_text() -> None:
    with pytest.raises(TypeError, match="Comment text must be a string"):
        Comment(42)  # type: ignore[arg-type]


def test_rawasp_rejects_non_string_text() -> None:
    with pytest.raises(TypeError, match="RawASP text must be a string"):
        RawASP(42)  # type: ignore[arg-type]


def test_blank_line_renders_as_empty_string() -> None:
    assert BlankLine().render() == ""


def test_rule_rejects_empty_head_and_body() -> None:
    with pytest.raises(ValueError, match="empty head and body"):
        Rule()
    with pytest.raises(ValueError, match="empty head and body"):
        Rule(body=[])  # falsy [] slips the None-only check


def test_annotate_appends_the_authoring_line_to_each_statement() -> None:
    program = ASPProgram()
    P = Predicate.define("p_ann", ["x"])
    Q = Predicate.define("q_ann", ["x"])
    here = _here()
    program.fact(Q(x=1))
    program.when(Q(x=1)).derive(P(x=1))
    fact_note = SourceLocation(here.filename, here.lineno + 1).display()
    rule_note = SourceLocation(here.filename, here.lineno + 2).display()
    lines = program.render(annotate=True).splitlines()
    assert f"q_ann(1).  % {fact_note}" in lines
    assert f"p_ann(1) :- q_ann(1).  % {rule_note}" in lines


def test_deepcopied_program_diverges_without_uninterning_values() -> None:
    # deepcopy(program) is a supported fork: the clone diverges freely, and
    # the Values inside remain the canonical interned objects (Value's
    # __deepcopy__ returns self), so identity-keyed uses stay safe
    program = ASPProgram()
    P = Predicate.define("p_fork", ["x"])
    program.fact(P(x=1))
    clone = copy.deepcopy(program)
    clone.fact(P(x=2))
    assert "p_fork(2)." in clone.render()
    assert "p_fork(2)." not in program.render()  # the original is untouched
    cloned_rule = next(iter(clone["Rules"]))
    assert isinstance(cloned_rule, Rule) and isinstance(cloned_rule.head, Predicate)
    assert cloned_rule.head["x"] is Number(1)  # still the cache resident


def test_formatting_elements_are_never_stamped() -> None:
    # No diagnostic can point at a comment or blank line, so they carry no
    # location — section() and friends do not pay the capture walk
    program = ASPProgram()
    program.section("layout")  # a blank line and a comment
    assert all(element.source_location is None for element in program["Rules"])


def test_annotate_leaves_comments_and_blank_lines_bare() -> None:
    program = ASPProgram()
    P = Predicate.define("p_nab", ["x"])
    program.comment("a note")
    program.blank_line()
    program.fact(P(x=1))
    lines = program.render(annotate=True).splitlines()
    # This file's location notes all share the "  % path:" suffix marker
    note_marker = f"  % {_here().display().rsplit(':', 1)[0]}:"
    noted = [line for line in lines if note_marker in line]
    # The fact carries the program's only note; the comment renders exactly
    # as written and the blank line after it stays empty
    assert len(noted) == 1 and noted[0].startswith("p_nab(1).")
    comment_index = lines.index("% a note")
    assert lines[comment_index + 1] == ""


def test_annotate_records_a_closer_on_a_different_line() -> None:
    program = ASPProgram()
    P = Predicate.define("p_far", ["x"])
    Q = Predicate.define("q_far", ["x"])
    here = _here()
    scene = program.when(Q(x=1))
    scene.derive(P(x=1))
    opened = SourceLocation(here.filename, here.lineno + 1).display()
    closed = SourceLocation(here.filename, here.lineno + 2).display()
    lines = program.render(annotate=True).splitlines()
    assert f"p_far(1) :- q_far(1).  % {opened} (closed at {closed})" in lines


def test_annotate_honors_mid_line_script_boundaries() -> None:
    # A #script block opening after a statement on the same line, or
    # closing with a statement after "#end." on the same line, is judged
    # character-wise: no note lands inside embedded source, and statements
    # after a mid-line close are annotated again
    program = ASPProgram()
    P = Predicate.define("p_msb", ["x"])
    program.raw_asp("q_msb(1). #script (python)\nimport clingo\n#end. q_msb(2).")
    program.fact(P(x=1))
    lines = program.render(annotate=True).splitlines()
    (import_line,) = [line for line in lines if "import clingo" in line]
    assert "%" not in import_line  # nothing stamped into the embedded source
    (fact_line,) = [line for line in lines if line.startswith("p_msb(1).")]
    assert "  % " in fact_line  # annotation resumes after the mid-line close


def test_annotate_preserves_line_numbering() -> None:
    # Notes are appended, never inserted: annotated line N is plain line N,
    # so the annotated text doubles as the reverse map for raw-clingo
    # errors. A multi-line raw block gets its origin on every non-blank
    # line; its interior blank line stays blank.
    program = ASPProgram()
    P = Predicate.define("p_num", ["x"])
    program.fact(P(x=1))
    program.comment("plain")
    program.raw_asp("raw_num(1).\n\nraw_num(2).")
    plain = program.render().splitlines()
    annotated = program.render(annotate=True).splitlines()
    assert len(plain) == len(annotated)
    assert all(a == p or a.startswith(f"{p}  % ") for p, a in zip(plain, annotated, strict=True))
    noted = [a for a in annotated if "  % " in a]
    assert len(noted) == 3  # the fact and both non-blank raw lines


def test_render_defaults_to_unannotated_output() -> None:
    program = ASPProgram()
    P = Predicate.define("p_ra", ["x"])
    program.fact(P(x=1))
    program.when(P(x=1)).derive(P(x=2))
    assert program.render() == program.render(annotate=False)


def test_annotate_is_inert_when_source_locations_are_off() -> None:
    program = ASPProgram(source_locations=False)
    P = Predicate.define("p_off", ["x"])
    Q = Predicate.define("q_off", ["x"])
    program.fact(Q(x=1))
    scene = program.when(Q(x=1))
    scene.derive(P(x=1))
    assert program.render(annotate=True) == program.render()


def test_render_lines_pairs_each_line_with_its_element() -> None:
    segment = Segment("Extras")
    P = Predicate.define("p_rl", ["x"])
    segment.fact(P(x=1))
    segment.raw_asp("raw_a(1).\nraw_b(2).")

    lines = segment.render_lines(with_header=True)
    assert [(line.text, line.element) for line in lines[:3]] == [
        ("", None),
        ("% ===== Extras =====", None),
        ("", None),
    ]
    assert lines[3].text == "p_rl(1)."
    assert isinstance(lines[3].element, Rule)
    # The multi-line raw block claims every one of its lines
    raw_lines = lines[4:]
    assert [line.text for line in raw_lines] == ["raw_a(1).", "raw_b(2)."]
    assert isinstance(raw_lines[0].element, RawASP)
    assert all(line.element is raw_lines[0].element for line in raw_lines)
    assert "\n".join(line.text for line in lines) == segment.render(with_header=True)

    bare = segment.render_lines(with_header=False)
    assert bare[0].text == "p_rl(1)."
    assert all(line.element is not None for line in bare)
    assert "\n".join(line.text for line in bare) == segment.render(with_header=False)


def test_annotate_leaves_script_block_interiors_bare() -> None:
    # A note inside a raw #script block would become part of the embedded
    # script's source; those lines stay bare, and annotation resumes after
    # the closing "#end."
    program = ASPProgram()
    P = Predicate.define("p_scr", ["x"])
    program.raw_asp('#script (python)\ndef main(prg):\n    prg.ground([("base", [])])\n#end.')
    program.fact(P(x=1))
    lines = program.render(annotate=True).splitlines()
    for bare in ("#script (python)", "def main(prg):", '    prg.ground([("base", [])])', "#end."):
        assert bare in lines  # exactly as written: no trailing note
    assert any(line.startswith("p_scr(1).  % ") for line in lines)  # annotation resumes


def test_header_gap_is_exactly_one_even_into_a_multiline_element() -> None:
    # The header's blank-absorption works on lines, so a first element that
    # OPENS with blank lines (a triple-quoted raw block) is trimmed too: the
    # gap after "% ===== name =====" is always exactly one blank line
    segment = Segment("Gap")
    segment.raw_asp("\n\nraw_gap(1).")
    rendered = segment.render(with_header=True)
    assert rendered == "\n% ===== Gap =====\n\nraw_gap(1)."


def test_assignable_attributes_validate_on_assignment() -> None:
    # project_shown/header/default_segment are the three assignable
    # attributes; assignment runs the same validation construction does, so
    # a bad value fails on the assigning line, not at render
    program = ASPProgram()
    with pytest.raises(TypeError, match="project_shown is a bool"):
        program.project_shown = "yes"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="header must be a string"):
        program.header = 7  # type: ignore[assignment]
    with pytest.raises(ValueError, match="single line"):
        program.header = "line1\nline2"  # would render bare uncommented ASP
    with pytest.raises(ValueError, match="single-line"):
        program.default_segment = "a\nb"
    program.header = "Set later"  # the happy paths still assign
    program.project_shown = True
    program.default_segment = "Elsewhere"
    P = Predicate.define("p_assign", ["x"])
    program.fact(P(x=1))
    rendered = program.render()
    assert "% Set later" in rendered
    assert "p_assign(1)." in rendered  # landed in the reassigned default segment
    assert program["Elsewhere"] is not None


def test_unknown_public_attribute_assignment_rejected() -> None:
    # A typo'd assignment must not silently configure nothing; the error
    # names the real assignable surface
    program = ASPProgram()
    with pytest.raises(AttributeError, match=r"no assignable attribute 'project_show'.*project_shown"):
        program.project_show = True  # type: ignore[attr-defined]
    with pytest.raises(AttributeError, match="no assignable attribute 'fact'"):
        program.fact = None  # type: ignore[method-assign, assignment]
    assert program.project_shown is False  # the typo configured nothing


def test_defined_constants_reads_back_a_copy() -> None:
    program = ASPProgram()
    program.define_constant("width", 9)
    program.define_constant("label", "grid")
    assert program.defined_constants == {"width": 9, "label": "grid"}
    snapshot = program.defined_constants
    snapshot["width"] = 0  # mutating the copy changes nothing
    assert program.defined_constants["width"] == 9
