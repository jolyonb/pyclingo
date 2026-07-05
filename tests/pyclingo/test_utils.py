"""
Tests for the collect_variables helper.
"""

import pytest

from pyclingo import Variable
from pyclingo.utils import collect_variables


def test_accepts_terms_sequences_and_tuples() -> None:
    X, Y = Variable("X"), Variable("Y")
    assert collect_variables((X, Y)) == {"X", "Y"}
    with pytest.raises(TypeError, match="got int"):
        collect_variables(42)  # type: ignore[arg-type]
