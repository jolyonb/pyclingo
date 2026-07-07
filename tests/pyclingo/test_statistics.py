"""
Tests for the statistics formatting contract: format_statistics reads a
specific schema out of clingo's stats dict; this names that dependency so a
clingo schema change fails here, not as an opaque KeyError in user code.
"""

from pyclingo import ASPProgram, Predicate


def test_format_statistics_renders_the_full_report() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    program.fact(*[P(x=i) for i in range(1, 4)])
    result = program.solve(models=0)
    list(result)
    report = result.format_statistics()
    # One anchor per section format_statistics reads
    for anchor in (
        "Models",
        "Time",
        "CPU Time",
        "Choices",
        "Conflicts",
        "Restarts",
        "Rules",
        "Atoms",
        "Bodies",
        "Equivalences",
        "Tight",
        "Variables",
        "Constraints",
    ):
        assert anchor in report, f"missing section: {anchor}"


def test_wall_time_present_in_raw_statistics() -> None:
    program = ASPProgram()
    P = Predicate.define("p2", ["x"])
    program.fact(P(x=1))
    result = program.solve()
    list(result)
    assert result.statistics is not None
    assert "wall_time" in result.statistics
