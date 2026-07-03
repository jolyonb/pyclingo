"""
Tests for model-count limits and wall-clock timeouts in ASPProgram.solve().
"""

import time

from pyclingo import ASPProgram, Choice, RangePool
from pyclingo.predicate import Predicate


def make_choice_program(n: int) -> ASPProgram:
    """A program with 2^n models: an unconstrained choice over a(1..n)."""
    program = ASPProgram()
    A = Predicate.define("a", ["value"])
    program.when(conditions=[], let=Choice(A(value=RangePool(1, n))))
    return program


def test_explicit_model_limit() -> None:
    program = make_choice_program(3)  # 8 models
    solutions = list(program.solve(models=2))
    assert len(solutions) == 2
    assert program.exhausted is False


def test_zero_means_enumerate_all() -> None:
    program = make_choice_program(3)  # 8 models
    solutions = list(program.solve(models=0))
    assert len(solutions) == 8
    assert program.exhausted is True
    assert program.satisfiable is True


def test_default_limit_does_not_truncate_small_spaces() -> None:
    program = make_choice_program(3)  # 8 models, well under the default of 1000
    solutions = list(program.solve())
    assert len(solutions) == 8
    assert program.exhausted is True


def test_timeout_yields_partial_results() -> None:
    # 2^60 models: unlimited enumeration can never finish, so the timeout must fire
    program = make_choice_program(60)
    start = time.monotonic()
    solutions = list(program.solve(models=0, timeout=1))
    elapsed = time.monotonic() - start
    assert len(solutions) > 0  # models found before the deadline were yielded
    assert program.exhausted is False
    assert program.satisfiable is True  # learned from the yielded models
    assert elapsed < 3  # cancelled promptly rather than enumerating forever


def test_no_timeout_unaffected() -> None:
    program = make_choice_program(2)  # 4 models
    solutions = list(program.solve(timeout=60))
    assert len(solutions) == 4
    assert program.exhausted is True


def test_early_close_finalizes_bookkeeping() -> None:
    program = make_choice_program(3)  # 8 models
    solutions = program.solve(models=0)
    first = next(solutions)
    assert isinstance(first, dict)
    solutions.close()
    assert program.exhausted is False  # we stopped early, truthfully reported
    assert program.satisfiable is True
    assert program.solution_count == 1
    assert "No statistics" not in program.format_statistics_clingo_style()


def test_second_solve_while_active_raises() -> None:
    import pytest

    program = make_choice_program(2)
    running = program.solve()
    with pytest.raises(RuntimeError, match="already in progress"):
        program.solve()
    running.close()
    # Releasing the generator makes the program solvable again
    assert len(list(program.solve())) == 4


def test_setup_errors_raise_at_call_time() -> None:
    import pytest

    from pyclingo import ASPProgram, Variable
    from pyclingo.predicate import Predicate

    program = ASPProgram()
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"])
    X, Y = Variable("X"), Variable("Y")
    program.when(conditions=P(x=X), let=Q(x=Y))  # Y is unsafe

    # The grounding error surfaces at the solve() call, not at first iteration
    with pytest.raises(RuntimeError):
        program.solve()
