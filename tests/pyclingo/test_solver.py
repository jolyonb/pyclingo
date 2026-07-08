import pytest

from pyclingo import ASPProgram, Predicate


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
    program.fact(TestPred(value=1), segment="Symbols")

    # A different casing is a different (nonexistent) segment
    with pytest.raises(ValueError, match="Segment 'SYMBOLS' does not exist"):
        program.fact(TestPred(value=2), segment="SYMBOLS")

    assert "test(1)." in program.render()


def test_default_segment_name_is_verbatim() -> None:
    program = ASPProgram(default_segment="MyRules")
    TestPred = Predicate.define("test", ["value"])
    program.fact(TestPred(value=1))  # the default segment self-creates

    with pytest.raises(ValueError, match="Segment 'MyRules' already exists"):
        program.add_segment("MyRules")
    with pytest.raises(KeyError, match="'myrules' does not exist"):
        program["myrules"]
