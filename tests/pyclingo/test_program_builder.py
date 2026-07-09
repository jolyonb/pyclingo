"""
Tests for ASPProgram's construction methods: fact, when, forbid,
raw_asp, define_constant, and the guards on their inputs.
"""

import pytest

from pyclingo import (
    ASPProgram,
    Choice,
    ConditionalLiteral,
    Count,
    DefinedConstant,
    Predicate,
    RangePool,
    Variable,
)
from pyclingo.program_elements import BlankLine, Comment, RawASP, Rule


def test_facts_must_be_grounded() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match=r"grounded.*variable\(s\) X"):
        program.fact(P(x=Variable("X")))


def test_builder_methods_reject_wrong_types() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="must be Predicate or Choice instances, got str"):
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


def test_fact_states_bare_choice_rules() -> None:
    # A bare choice rule is a legitimate unconditional statement, so fact()
    # takes it alongside grounded predicates
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    program.fact(Choice(P(x=RangePool(1, 3))))
    assert "{ p(1..3) }." in program.render()


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
    # error caught at construction
    P = Predicate.define("p_cl", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match="at least one condition"):
        ConditionalLiteral(P(x=X), [])


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
    program.fact(choice)
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
    with pytest.raises(ValueError, match="quotes, backslashes, or newlines"):
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
    with pytest.raises(RuntimeError, match="parsing"):
        program.ground()


def test_ground_wraps_a_grounding_error() -> None:
    program = ASPProgram()
    program.raw_asp("p(X) :- q(Y).")  # X unbound in the head — unsafe at ground time
    with pytest.raises(RuntimeError, match="Grounding failed"):
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
