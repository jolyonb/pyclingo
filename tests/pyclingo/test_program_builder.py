"""
Tests for ASPProgram's construction methods: fact, when, forbid,
raw_asp, define_constant, and the guards on their inputs.
"""

import pytest

from pyclingo import ASPProgram, Choice, ConditionalLiteral, Count, Predicate, RangePool, Variable


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


def test_multiline_segment_name_rejected() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="single-line"):
        program.add_segment("a\nb")


def test_not_reserved_as_constant_name() -> None:
    program = ASPProgram()
    with pytest.raises(ValueError, match="reserved"):
        program.define_constant("not", 1)


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
