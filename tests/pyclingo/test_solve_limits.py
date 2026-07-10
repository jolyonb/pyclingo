"""
Tests for consumer-side stream limits, wall-clock timeouts, and the
SolveResult lifecycle.
"""

import time
from itertools import islice
from typing import Any, cast

import clingo
import pytest

from pyclingo import ASPProgram, Choice, Predicate, RangePool, Variable
from pyclingo.clingo_handler import ClingoMessageHandler


def make_choice_program(n: int) -> ASPProgram:
    """A program with 2^n models: an unconstrained choice over a(1..n)."""
    program = ASPProgram()
    A = Predicate.define("a", ["value"])
    program.choose(Choice(A(value=RangePool(1, n))))
    return program


def test_consumer_side_limit() -> None:
    # The stream is unbounded; the consumer's consumption is the limit
    result = make_choice_program(3).solve()  # 8 models exist
    assert len(list(islice(result, 2))) == 2
    assert result.exhausted is False  # more may exist: we stopped, it didn't


def test_full_consumption_enumerates_all() -> None:
    result = make_choice_program(3).solve()  # 8 models
    assert len(list(result)) == 8
    assert result.exhausted is True
    assert result.satisfiable is True


def test_take_one_model() -> None:
    # The one-model ask is next(iter(...)); laziness means the search
    # suspends after the first model — nothing runs ahead of consumption
    result = make_choice_program(3).solve()  # 8 models exist
    model = next(iter(result))
    assert len(model) >= 0
    assert result.models_yielded == 1
    assert result.exhausted is False


def test_timeout_yields_partial_results() -> None:
    # 2^60 models: unlimited enumeration can never finish, so the timeout must fire
    result = make_choice_program(60).solve(timeout=0.2)
    start = time.monotonic()
    # islice bound: if the timeout machinery regressed to never firing,
    # this fails loudly instead of hanging the suite on 2^60 models
    models = list(islice(result, 100_000))
    elapsed = time.monotonic() - start
    assert len(models) > 0  # models found before the deadline were yielded
    assert result.exhausted is False
    assert result.timed_out is True  # the deadline ended it, not the caller
    assert result.satisfiable is True  # learned from the yielded models
    assert elapsed < 2  # cancelled promptly rather than enumerating forever


def test_no_timeout_unaffected() -> None:
    result = make_choice_program(2).solve(timeout=60)  # 4 models
    assert len(list(result)) == 4
    assert result.exhausted is True
    assert result.timed_out is False


def test_early_close_finalizes_bookkeeping() -> None:
    result = make_choice_program(3).solve()  # 8 models
    next(iter(result))  # a choice model may legitimately be the empty set
    result.close()
    assert result.exhausted is False  # we stopped early, truthfully reported
    assert result.satisfiable is True
    assert result.models_yielded == 1
    assert "No statistics" not in result.format_statistics()


def test_context_manager_closes() -> None:
    program = make_choice_program(3)
    with program.solve() as result:
        next(iter(result))
    assert result.models_yielded == 1
    assert result.exhausted is False


def test_repeated_solves_are_independent() -> None:
    # Each solve() returns its own SolveResult; nothing is shared or locked
    program = make_choice_program(2)
    first = program.solve()
    second = program.solve()
    assert len(list(second)) == 4
    assert len(list(first)) == 4
    assert first.exhausted and second.exhausted
    assert first.models_yielded == second.models_yielded == 4


def test_unconsumed_result_reports_honestly() -> None:
    result = make_choice_program(2).solve()
    assert result.satisfiable is None  # never iterated: nothing learned
    assert result.models_yielded == 0
    assert result.format_statistics() == "No statistics available"


def test_negative_timeout_rejected() -> None:
    program = make_choice_program(2)
    with pytest.raises(ValueError, match="non-negative"):
        program.solve(timeout=-5)


def test_timeout_anchors_at_first_iteration() -> None:
    # Time between solve() and iteration belongs to the caller: the budget
    # must not burn while clingo sits idle
    result = make_choice_program(3).solve(timeout=0.2)
    time.sleep(0.4)  # longer than the entire timeout
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
    result = make_choice_program(3).solve()  # 8 models
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


def test_solve_phase_messages_attach_instead_of_halting() -> None:
    # No known clingo 5.8 construct emits solve-phase messages in API mode,
    # so this injects into the handler between models to test the plumbing:
    # each Model carries the batch that arrived while it was being found,
    # and the result accumulates them all
    program = make_choice_program(2)  # 4 models
    result = program.solve()
    iterator = iter(result)
    first = next(iterator)
    assert first.messages == []

    # Reach through the close-checking wrapper to the generator's frame;
    # the runtime types are known
    frame = cast(Any, result._iterator)._generator.gi_frame
    handler = frame.f_locals["message_handler"]
    assert isinstance(handler, ClingoMessageHandler)
    handler.on_message(clingo.MessageCode.Other, "info: something mid-solve")

    second = next(iterator)
    assert len(second.messages) == 1
    assert "mid-solve" in second.messages[0].message
    list(iterator)  # exhaust
    assert len(result.messages) == 1


def test_timeout_before_any_model_raises() -> None:
    # Quiet while real answers are in hand, loud when empty-handed: a
    # silent empty stream would read as unsatisfiable
    program = make_choice_program(1)
    A = Predicate.define("h_pig", ["p", "h"])
    B = Predicate.define("h_p", ["p"], show=False)
    P, P2, H = Variable("P"), Variable("P2"), Variable("H")
    program.fact(*[B(p=i) for i in range(1, 15)])
    program.when(B(p=P)).derive(Choice(A(p=P, h=RangePool(1, 13))).exactly(1))
    program.forbid(A(p=P, h=H), A(p=P2, h=H), P < P2)
    result = program.solve(timeout=0.05)
    with pytest.raises(TimeoutError, match="no model within"):
        list(result)
    assert result.satisfiable is None
    assert not result.exhausted


def test_held_iterator_is_loud_after_close() -> None:
    # A generator closed early can only StopIteration on resume, which a
    # held iterator would read as exhaustion; the wrapper raises instead
    result = make_choice_program(3).solve()
    iterator = iter(result)
    next(iterator)
    result.close()
    with pytest.raises(RuntimeError, match="was closed"):
        next(iterator)
    # Natural exhaustion keeps normal iterator protocol: StopIteration forever
    finished = make_choice_program(1).solve()
    iterator = iter(finished)
    assert len(list(iterator)) == 2
    with pytest.raises(StopIteration):
        next(iterator)
    finished.close()  # close after natural end changes nothing
    with pytest.raises(StopIteration):
        next(iterator)


def test_nan_timeout_rejected() -> None:
    grounded = make_choice_program(1).ground()
    with pytest.raises(ValueError, match="timeout"):
        grounded.solve(timeout=float("nan"))


def test_iterator_direct_close_is_loud_too() -> None:
    # contextlib.closing habits call close() on the iterator itself; that
    # path must set the closed flag like the handle's close() does
    result = make_choice_program(3).solve()
    iterator = iter(result)
    next(iterator)
    iterator.close()  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="was closed"):
        next(iterator)


def test_interleaved_results_stay_independent() -> None:
    # Two live streams advanced in lockstep must not consume or corrupt one
    # another: each SolveResult owns its own search state. (Sequential
    # independence is weaker — this alternates next() calls mid-stream.)
    program = make_choice_program(2)  # 4 models each
    ra, rb = program.solve(), program.solve()
    a, b = iter(ra), iter(rb)
    na = [next(a)]
    nb = [next(b)]
    na.append(next(a))  # advance a again while b sits mid-stream
    na += list(a)
    nb += list(b)  # b resumes from where it paused, unaffected by a
    assert len(na) == 4 and len(nb) == 4
    assert ra.exhausted and rb.exhausted
    assert ra.models_yielded == rb.models_yielded == 4


def test_held_iterator_is_loud_after_timeout() -> None:
    # A generator dead from a TimeoutError can only StopIteration on resume,
    # which a retry loop reusing the held iterator would read as a clean
    # empty stream — i.e. unsatisfiable. The timeout terminals close the
    # state first, so the wrapper stays loud.
    program = make_choice_program(1)
    A = Predicate.define("h2_pig", ["p", "h"])
    B = Predicate.define("h2_p", ["p"], show=False)
    P, P2, H = Variable("P"), Variable("P2"), Variable("H")
    program.fact(*[B(p=i) for i in range(1, 15)])
    program.when(B(p=P)).derive(Choice(A(p=P, h=RangePool(1, 13))).exactly(1))
    program.forbid(A(p=P, h=H), A(p=P2, h=H), P < P2)
    result = program.solve(timeout=0.05)
    iterator = iter(result)
    with pytest.raises(TimeoutError):
        next(iterator)
    with pytest.raises(RuntimeError, match="was closed"):
        next(iterator)


def test_scalar_knobs_reject_lookalike_types() -> None:
    # timeout=True silently meant one second; max_iterations=True meant 1
    program = make_choice_program(1)
    with pytest.raises(TypeError, match="timeout is seconds"):
        program.solve(timeout=True)
    grounded = make_choice_program(1).ground()
    with pytest.raises(TypeError, match="max_iterations is a count"):
        grounded.cautious(max_iterations=True)
    optimizing = ASPProgram()
    B = Predicate.define("b_knob", ["x"])
    optimizing.choose(Choice(B(x=RangePool(1, 2))).at_least(1))
    optimizing.minimize(1, Variable("X"), condition=B(x=Variable("X")))
    with pytest.raises(TypeError, match="max_iterations is a count"):
        optimizing.ground().optimize(max_iterations=True)


def test_scalar_knobs_fail_before_grounding_is_paid_for() -> None:
    # The program below cannot even render (dangling when); a bad timeout
    # or count must be reported first — cheap checks precede grounding
    program = ASPProgram()
    P = Predicate.define("p_cheap", ["x"])
    program.when(P(x=1))  # deliberately left unclosed
    with pytest.raises(TypeError, match="timeout is seconds"):
        program.solve(timeout="5")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="max_iterations is a count"):
        program.cautious(max_iterations="3")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="max_iterations is a count"):
        program.optimize(max_iterations="3")  # type: ignore[arg-type]
    program.when(P(x=1)).derive(P(x=2))  # close a fresh when; the original stays pending
    with pytest.raises(ValueError, match="incomplete when"):
        program.render()  # the dangling when() is still the render's complaint
