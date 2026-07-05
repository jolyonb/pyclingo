"""
Tests for the content rules of Number, String, and pools.
"""

import pytest

from pyclingo.core import Number, RangePool, String, pool


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
