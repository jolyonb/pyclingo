"""
Tests for model-count limits, wall-clock timeouts, and SolveResult lifecycle.
"""

import time

import pytest

from pyclingo import ASPProgram, Choice, RangePool, Variable
from pyclingo.predicate import Predicate


def make_choice_program(n: int) -> ASPProgram:
    """A program with 2^n models: an unconstrained choice over a(1..n)."""
    program = ASPProgram()
    A = Predicate.define("a", ["value"])
    program.fact(Choice(A(value=RangePool(1, n))))
    return program


def test_explicit_model_limit() -> None:
    result = make_choice_program(3).solve(models=2)  # 8 models exist
    assert len(list(result)) == 2
    assert result.exhausted is False


def test_zero_means_enumerate_all() -> None:
    result = make_choice_program(3).solve(models=0)  # 8 models
    assert len(list(result)) == 8
    assert result.exhausted is True
    assert result.satisfiable is True


def test_default_limit_does_not_truncate_small_spaces() -> None:
    result = make_choice_program(3).solve()  # 8 models, well under the default of 1000
    assert len(list(result)) == 8
    assert result.exhausted is True


def test_timeout_yields_partial_results() -> None:
    # 2^60 models: unlimited enumeration can never finish, so the timeout must fire
    result = make_choice_program(60).solve(models=0, timeout=1)
    start = time.monotonic()
    models = list(result)
    elapsed = time.monotonic() - start
    assert len(models) > 0  # models found before the deadline were yielded
    assert result.exhausted is False
    assert result.satisfiable is True  # learned from the yielded models
    assert elapsed < 3  # cancelled promptly rather than enumerating forever


def test_no_timeout_unaffected() -> None:
    result = make_choice_program(2).solve(timeout=60)  # 4 models
    assert len(list(result)) == 4
    assert result.exhausted is True


def test_early_close_finalizes_bookkeeping() -> None:
    result = make_choice_program(3).solve(models=0)  # 8 models
    next(iter(result))  # a choice model may legitimately be the empty set
    result.close()
    assert result.exhausted is False  # we stopped early, truthfully reported
    assert result.satisfiable is True
    assert result.solution_count == 1
    assert "No statistics" not in result.format_statistics()


def test_context_manager_closes() -> None:
    program = make_choice_program(3)
    with program.solve(models=0) as result:
        next(iter(result))
    assert result.solution_count == 1
    assert result.exhausted is False


def test_repeated_solves_are_independent() -> None:
    # Each solve() returns its own SolveResult; nothing is shared or locked
    program = make_choice_program(2)
    first = program.solve()
    second = program.solve()
    assert len(list(second)) == 4
    assert len(list(first)) == 4
    assert first.exhausted and second.exhausted
    assert first.solution_count == second.solution_count == 4


def test_unconsumed_result_reports_honestly() -> None:
    result = make_choice_program(2).solve()
    assert result.satisfiable is None  # never iterated: nothing learned
    assert result.solution_count == 0
    assert result.format_statistics() == "No statistics available"


def test_setup_errors_raise_at_call_time() -> None:
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"])
    X, Y = Variable("X"), Variable("Y")
    program.when(conditions=P(x=X), let=Q(x=Y))  # Y is unsafe

    # The grounding error surfaces at the solve() call, not at first iteration
    with pytest.raises(RuntimeError):
        program.solve()


def test_grounding_diagnostics_ride_in_the_error() -> None:
    # An info-level message (q never appears in a head) halts at the default
    # threshold, and the formatted diagnostics are part of the raised error
    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"])
    program.when(conditions=Q(x=1), let=P(x=1))
    with pytest.raises(RuntimeError, match="does not occur"):
        program.solve()


def test_negative_timeout_rejected() -> None:
    program = make_choice_program(2)
    with pytest.raises(ValueError, match="non-negative"):
        program.solve(timeout=-5)


def test_timeout_anchors_at_first_iteration() -> None:
    # Time between solve() and iteration belongs to the caller: the budget
    # must not burn while clingo sits idle
    result = make_choice_program(3).solve(models=0, timeout=1)
    time.sleep(1.3)  # longer than the entire timeout
    assert len(list(result)) == 8
    assert result.exhausted is True


def test_iterating_a_consumed_result_raises() -> None:
    result = make_choice_program(2).solve()
    assert len(list(result)) == 4
    with pytest.raises(RuntimeError, match="already consumed"):
        list(result)


def test_closed_result_raises_on_iteration() -> None:
    result = make_choice_program(2).solve()
    next(iter(result))
    result.close()
    with pytest.raises(RuntimeError, match="already consumed"):
        list(result)


def test_break_and_resume_still_works() -> None:
    # Partial consumption is a legitimate streaming pattern: breaking out of
    # a loop and iterating again continues the same stream
    result = make_choice_program(3).solve(models=0)  # 8 models
    seen = 0
    for _model in result:
        seen += 1
        if seen == 3:
            break
    remaining = len(list(result))
    assert seen + remaining == 8


def test_closing_before_any_iteration_still_marks_consumed() -> None:
    result = make_choice_program(2).solve()
    result.close()
    with pytest.raises(RuntimeError, match="already consumed"):
        list(result)
