"""
Tests for the content rules of Number, String, and pools.
"""

import pytest

from pyclingo import ANY, ASPProgram, DefinedConstant, Number, Predicate, RangePool, String, V, Value, Variable, pool


def test_number_range_matches_clingo() -> None:
    # clingo silently wraps integers outside 32 bits; we refuse them instead
    Number(2**31 - 1)
    Number(-(2**31))
    with pytest.raises(ValueError, match="outside clingo's integer range"):
        Number(2**31)


def test_string_content_rules() -> None:
    with pytest.raises(ValueError, match="backslash"):
        String("back\\slash")
    with pytest.raises(ValueError, match="backslash"):
        String("multi\nline")
    with pytest.raises(ValueError, match="double quotes"):
        String('has "quotes"')
    assert String("it's fine").render() == '"it\'s fine"'  # single quotes are legal text


def test_range_bounds_must_be_integer_valued() -> None:
    with pytest.raises(TypeError, match="Range start"):
        RangePool(String("a"), String("z"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Range start"):
        RangePool(String("a"), 5)  # type: ignore[arg-type]


def test_empty_pools_raise_everywhere() -> None:
    with pytest.raises(ValueError, match="empty"):
        pool(range(1, 1))
    with pytest.raises(ValueError, match="empty"):
        pool(range(2, 2, 2))
    with pytest.raises(ValueError, match="empty"):
        pool([])


def test_cache_can_be_cleared() -> None:
    before = Variable("CacheProbe")
    assert Variable("CacheProbe") is before
    Value.clear_cache()
    after = Variable("CacheProbe")
    assert after is not before  # identity resets across a clear
    assert Variable("CacheProbe") is after  # caching resumes


def test_failed_construction_does_not_poison_the_cache() -> None:
    before = len(Value._cache)
    with pytest.raises(ValueError):
        Variable("lowercase_bad")
    assert len(Value._cache) == before


def test_inverted_range_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        RangePool(5, 1)


def test_non_ascii_variable_and_constant_names_rejected() -> None:
    with pytest.raises(ValueError, match="ASCII"):
        Variable("Ärger")
    with pytest.raises(ValueError, match="ASCII"):
        DefinedConstant("größe")


def test_vars_attribute_factory() -> None:
    # V.X IS Variable("X") — the cache makes them the same object
    assert V.X is Variable("X")
    assert V.Cell.render() == "Cell"
    with pytest.raises(ValueError, match="uppercase"):
        V.cell  # noqa: B018 (the attribute access is the act under test)


def test_variable_indexing_derives_names() -> None:
    X = Variable("X")
    assert X[1] is Variable("X_1")
    assert X[1][2].render() == "X_1_2"
    assert V.Adj[3].render() == "Adj_3"
    assert X["adj"] is Variable("X_adj")
    assert X[1]["lo"].render() == "X_1_lo"
    with pytest.raises(TypeError, match="non-negative int"):
        X[-1]
    with pytest.raises(TypeError, match="int or a str"):
        X[1.5]  # type: ignore[index]
    with pytest.raises(ValueError, match="uppercase"):
        ANY[1]  # "_" + "_1" would be a leading-underscore name


def test_derived_and_factory_names_inherit_variable_validation() -> None:
    # Both paths construct Variable(name), so the constructor's rules —
    # ASCII, capitalization, character set — apply automatically
    X = Variable("X")
    with pytest.raises(ValueError, match="ASCII"):
        X["ünter"]
    with pytest.raises(ValueError, match="letters, digits, and underscores"):
        X["a-b"]
    assert X[""] is X  # the empty suffix is the identity, so an optional suffix needs no guard
    with pytest.raises(ValueError, match="ASCII"):
        V.Ünter  # noqa: B018 (the attribute access is the act under test)


def test_vars_in_a_real_rule() -> None:
    P = Predicate.define("p_vars", ["a", "b"])
    Q = Predicate.define("q_vars", ["a"])
    program = ASPProgram()
    program.fact(P(a=1, b=2))
    program.when(P(a=V.X, b=V.Y), V.X < V.Y).derive(Q(a=V.X))
    model = next(iter(program.solve()))
    assert [a["a"].value for a in model.atoms(Q)] == [1]
