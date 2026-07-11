"""
Tests for the suite-wide render conformance checker itself.
"""

import pytest

from pyclingo import (
    ASPProgram,
    Count,
    DefinedConstant,
    ExplicitPool,
    Number,
    Predicate,
    RangePool,
    Segment,
    String,
    Variable,
)
from tests.conftest import _TERM_HOSTS, assert_clingo_accepts


def test_checker_accepts_valid_programs() -> None:
    assert_clingo_accepts("p(1..3). q(X) :- p(X), not X < 2.")


def test_checker_rejects_invalid_programs() -> None:
    with pytest.raises(pytest.fail.Exception, match="not valid clingo"):
        assert_clingo_accepts("q(X) :- p(X), not (X < 2).")


def test_checker_is_active_by_default() -> None:
    assert ASPProgram.render.__name__ == "checked_program_render"
    assert Segment.render.__name__ == "checked_segment_render"  # segment fragments are covered too


@pytest.mark.allow_invalid_render
def test_marker_opts_out_of_the_checker() -> None:
    assert ASPProgram.render.__name__ == "render"


def test_top_level_term_renders_are_wrapped_and_checked() -> None:
    # The patched render parse-checks direct term assertions; valid terms pass
    X = Variable("X")
    P = Predicate.define("p", ["x"])
    assert (~P(x=1)).render() == "not p(1)"
    assert (~(X < 5)).render() == "X >= 5"  # comparisons normalize (see Not)
    assert Count(X, condition=P(x=X)).render() == "#count{ X : p(X) }"


def test_every_term_host_family_resolves_to_the_checked_render() -> None:
    # The patch must land on the class whose render an INSTANCE actually
    # calls: concrete Value/Pool subclasses define their own render, which
    # once shadowed the base-class patch and silently turned the checker
    # off for both families
    instances = [
        Variable("ConfCheck"),
        Number(3),
        String("conf"),
        DefinedConstant("conf_c"),
        RangePool(1, 3),
        ExplicitPool([1, 2]),
        Predicate.define("p_conf", ["x"])(x=1),
        Count(Variable("ConfCheck")),
    ]
    for instance in instances:
        assert type(instance).render.__name__ == "checked_render", type(instance).__name__
    # And every family listed in _TERM_HOSTS is patched at its root too
    for term_class, _host in _TERM_HOSTS:
        if "render" in term_class.__dict__:
            assert term_class.render.__name__ in ("checked_render", "checked_program_render"), term_class.__name__


def test_segment_fragment_renders_are_parse_checked() -> None:
    # Direct segment-render assertions are the one rendered text the program
    # patch never sees; the Segment patch must catch an invalid fragment
    program = ASPProgram()
    P = Predicate.define("p_segchk", ["x"])
    program.fact(P(x=1))
    (segment,) = program.segments
    assert "p_segchk(1)." in segment.render()  # a valid fragment passes through
    bad = Segment("bad_fragment")
    bad.raw_asp("p_segchk(1) :-")  # legal to hold (raw text is unparsed)...
    with pytest.raises(pytest.fail.Exception, match="not valid clingo"):
        bad.render()  # ...but a rendered fragment must parse


def test_nested_renders_do_not_multiply_checks() -> None:
    # A full program render recurses through term renders; only the outermost
    # parse fires (this is a smoke test that nothing raises and output is sane)
    P = Predicate.define("p", ["x"])
    program = ASPProgram()
    program.fact(P(x=1))
    assert "p(1)." in program.render()
