import pytest

from pyclingo import ASPProgram
from pyclingo.predicate import Predicate


def test_case_insensitive_segments() -> None:
    """Test that segment names are case-insensitive to prevent duplicates."""
    program = ASPProgram()

    # Add a segment with mixed case
    program.add_segment("Symbols")

    # Attempting to add the same segment with different case should fail
    with pytest.raises(ValueError, match="Segment 'symbols' already exists"):
        program.add_segment("symbols")

    with pytest.raises(ValueError, match="Segment 'SYMBOLS' already exists"):
        program.add_segment("SYMBOLS")


def test_case_insensitive_segment_content_merging() -> None:
    """Test that content added to segments with different cases gets merged."""
    program = ASPProgram()

    # Create a test predicate
    TestPred = Predicate.define("test", ["value"])

    # Add segment and initial content
    program.add_segment("Symbols")
    program.fact(TestPred(value=1), segment="Symbols")

    # Add content using different case - should go to same segment
    program.fact(TestPred(value=2), segment="symbols")
    program.fact(TestPred(value=3), segment="SYMBOLS")

    # Render and check that all facts are together
    rendered = program.render()

    # All facts should appear in the output
    assert "test(1)." in rendered
    assert "test(2)." in rendered
    assert "test(3)." in rendered


def test_default_segment_case_normalization() -> None:
    """Test that default segment is also normalized to lowercase."""
    program = ASPProgram(default_segment="MyRules")

    TestPred = Predicate.define("test", ["value"])

    # Add fact to default segment
    program.fact(TestPred(value=1))

    # Try to add a segment with the same name in different case - should fail
    with pytest.raises(ValueError, match="Segment 'myrules' already exists"):
        program.add_segment("myrules")
