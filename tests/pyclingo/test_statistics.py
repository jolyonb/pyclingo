"""
Tests for the statistics formatting contract: format_statistics reads a
specific schema out of clingo's stats dict; this names that dependency so a
clingo schema change fails here, not as an opaque KeyError in user code.
"""

from copy import deepcopy
from itertools import islice

from pyclingo import ASPProgram, Choice, Predicate, RangePool
from pyclingo.statistics import format_statistics_clingo_style


def test_format_statistics_renders_the_full_report() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    program.fact(*[P(x=i) for i in range(1, 4)])
    result = program.solve()
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


def test_atoms_line_shows_auxiliary_breakdown() -> None:
    program = ASPProgram()
    P = Predicate.define("p3", ["x"])
    program.fact(*[P(x=i) for i in range(1, 4)])
    result = program.solve()
    list(result)
    assert result.statistics is not None
    stats = deepcopy(result.statistics)
    stats["problem"]["lp"]["atoms"] = 10
    stats["problem"]["lp"]["atoms_aux"] = 4
    report = format_statistics_clingo_style(stats)
    assert "Auxiliary: 4" in report
    assert "Original: 6" in report


def test_constraints_line_shows_percentage_breakdown() -> None:
    program = ASPProgram()
    P = Predicate.define("p4", ["x"])
    program.fact(*[P(x=i) for i in range(1, 4)])
    result = program.solve()
    list(result)
    assert result.statistics is not None
    stats = deepcopy(result.statistics)
    stats["problem"]["generator"]["constraints_binary"] = 5
    stats["problem"]["generator"]["constraints_ternary"] = 3
    stats["problem"]["generator"]["constraints"] = 2
    report = format_statistics_clingo_style(stats)
    assert "Constraints  : 10" in report
    assert "Binary:" in report
    assert "Ternary:" in report
    assert "Other:" in report


def test_statistics_finalize_after_a_capped_run() -> None:
    # A capped run (consume a few, then close) finalizes bookkeeping — stats
    # are not gated on full enumeration. The search must END first: a merely
    # paused stream (islice with no close) is still live and has no final
    # stats yet; the with-block's close ends it and finalizes them.
    program = ASPProgram()
    P = Predicate.define("p_cap", ["x"])
    program.choose(Choice(P(x=RangePool(1, 4))))  # 2^4 models
    with program.solve() as result:
        list(islice(result, 3))
        assert result.statistics is None  # still live mid-stream: no final stats
    assert not result.exhausted  # closed early, not exhausted
    assert result.statistics is not None and "wall_time" in result.statistics
    assert "No statistics" not in result.format_statistics()


def test_statistics_finalize_after_a_timeout() -> None:
    # A timed-out run still populates statistics: finalization is not gated on
    # clean exhaustion
    program = ASPProgram()
    P = Predicate.define("p_timeout", ["x"])
    program.choose(Choice(P(x=RangePool(1, 60))))  # 2^60 models: never finishes
    result = program.solve(timeout=0.2)
    # islice bound: a timeout regression fails loudly instead of hanging
    list(islice(result, 100_000))
    assert not result.exhausted
    assert result.statistics is not None and "wall_time" in result.statistics


def test_statistics_property_returns_a_copy() -> None:
    # Caller mutation must not corrupt the handle or format_statistics()
    program = ASPProgram()
    P = Predicate.define("p_stat_copy", ["x"])
    program.fact(P(x=1))
    result = program.solve()
    list(result)
    snapshot = result.statistics
    assert snapshot is not None
    snapshot.clear()
    fresh = result.statistics
    assert fresh is not None and "wall_time" in fresh
    assert "wall_time" in result.format_statistics() or "Time" in result.format_statistics()
