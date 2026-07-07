"""
Tests for the ground()/solve() split: ground once, solve many times, with
the sequential-solve and staleness contracts enforced loudly.
"""

import clingo
import pytest

from pyclingo import ASPProgram, Choice, Predicate, RangePool


def make_program(n: int = 3) -> ASPProgram:
    """2^n models: an unconstrained choice over a(1..n)."""
    program = ASPProgram()
    A = Predicate.define("a", ["value"])
    program.fact(Choice(A(value=RangePool(1, n))))
    return program


def test_ground_once_solve_repeatedly() -> None:
    grounded = make_program().ground()
    first = grounded.solve(models=0)
    assert len(list(first)) == 8
    second = grounded.solve(models=0)
    assert len(list(second)) == 8
    assert first.exhausted and second.exhausted


def test_per_solve_settings_on_one_grounding() -> None:
    grounded = make_program().ground()
    assert len(list(grounded.solve(models=0))) == 8
    assert len(list(grounded.solve(models=2))) == 2
    assert len(list(grounded.solve())) == 1  # the default, per solve


def test_overlapping_solves_rejected() -> None:
    grounded = make_program().ground()
    first = grounded.solve(models=0)
    next(iter(first))  # started but unconsumed
    with pytest.raises(RuntimeError, match="still open"):
        grounded.solve()
    first.close()
    assert grounded.solve() is not None  # closed counts as finished


def test_grounding_is_an_independent_snapshot() -> None:
    # Like a compiled regex: the handle holds the text it was made from,
    # unaffected by later mutation of the program
    program = make_program()
    P = Predicate.define("p_extra", ["x"], show=False)
    Q = Predicate.define("q_extra", ["x"])
    before = program.ground()
    program.fact(P(x=1))
    program.when(P(x=1), let=Q(x=1))
    after = program.ground()
    assert "p_extra" not in before.text
    assert "p_extra" in after.text
    # Both handles solve their own program — side-by-side comparison works
    model_before = next(iter(before.solve()))
    model_after = next(iter(after.solve()))
    assert model_before.atoms(Q) == []
    assert len(model_after.atoms(Q)) == 1


def test_one_shot_solve_unchanged() -> None:
    # solve() is sugar for ground().solve(); behavior identical
    result = make_program().solve(models=0)
    assert len(list(result)) == 8
    assert result.statistics is not None
    assert "wall_time" in result.statistics


def test_messages_window_per_solve_on_shared_handler() -> None:
    # The handler is shared across a grounding's solves; each result sees
    # only messages arriving within its own window (index snapshots, not
    # clearing). Injection stands in for solve-phase messages.
    grounded = make_program().ground()

    first = grounded.solve(models=0)
    iterator = iter(first)
    next(iterator)
    handler = grounded._message_handler
    handler.on_message(clingo.MessageCode.Other, "info: during first solve")
    list(iterator)
    assert len(first.messages) == 1

    second = grounded.solve(models=0)
    list(second)
    assert second.messages == []  # the first solve's message is outside its window


def test_abandon_frees_the_grounding() -> None:
    grounded = make_program().ground()
    first = grounded.solve(models=0)
    next(iter(first))  # open and unconsumed
    grounded.abandon()
    assert first.finished
    assert len(list(grounded.solve(models=0))) == 8


def test_abandon_is_idempotent_and_safe_when_nothing_is_open() -> None:
    grounded = make_program().ground()
    grounded.abandon()  # nothing open: no-op
    result = grounded.solve(models=0)
    list(result)
    grounded.abandon()  # already finished: no-op
    grounded.abandon()
    assert len(list(grounded.solve(models=2))) == 2
