"""
Tests for the ground()/solve() split: ground once, solve many times, with
the sequential-solve and staleness contracts enforced loudly.
"""

import clingo
import pytest

from pyclingo import ASPProgram, Choice, Number, Predicate, RangePool, Variable

A = Predicate.define("a", ["value"])


def make_program(n: int = 3) -> ASPProgram:
    """2^n models: an unconstrained choice over a(1..n)."""
    program = ASPProgram()
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
    # The handler is shared across a grounding's solves; each solve clears
    # the list at start (the sequential guard proves nobody is mid-window),
    # and each result sees only messages arriving within its own window.
    # Injection stands in for solve-phase messages.
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
    assert second.messages == []  # the first solve's message was cleared
    assert grounded._message_handler.messages == []  # nothing accumulates across solves


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


def test_assumptions_filter_models_per_solve() -> None:
    grounded = make_program().ground()  # {a(1..3)}: 8 models
    assert len(list(grounded.solve(models=0, assumptions=[A(value=1)]))) == 4
    assert len(list(grounded.solve(models=0, assumptions=[~A(value=1)]))) == 4
    assert len(list(grounded.solve(models=0, assumptions=[A(value=1), ~A(value=2)]))) == 2
    # Assumptions never persist: the next solve is unconstrained
    assert len(list(grounded.solve(models=0))) == 8


def test_assumed_atoms_appear_in_every_model() -> None:
    grounded = make_program().ground()
    for model in grounded.solve(models=0, assumptions=[A(value=2)]):
        assert A(value=2) in set(model.atoms(A))


def test_assuming_a_fact_false_is_unsat() -> None:
    program = ASPProgram()
    F = Predicate.define("f_assume", ["x"])
    program.fact(F(x=9))
    grounded = program.ground()
    result = grounded.solve(assumptions=[~F(x=9)])
    assert list(result) == []
    assert result.satisfiable is False


def test_absent_atom_assumption_raises_with_teaching() -> None:
    grounded = make_program().ground()
    Ghost = Predicate.define("ghost", ["x"])
    with pytest.raises(ValueError, match="does not occur in this grounding"):
        grounded.solve(assumptions=[Ghost(x=7)])
    with pytest.raises(ValueError, match="does not occur in this grounding"):
        grounded.solve(assumptions=[~Ghost(x=7)])


def test_ungrounded_and_wrong_type_assumptions_rejected() -> None:
    grounded = make_program().ground()
    X = Variable("X")
    with pytest.raises(ValueError, match="must be grounded"):
        grounded.solve(assumptions=[A(value=X)])
    with pytest.raises(TypeError, match="predicate atoms"):
        grounded.solve(assumptions=[X == 1])  # type: ignore[list-item]


def test_assumptions_resolve_defined_constants() -> None:
    # gringo substitutes #const at grounding, so the ground atom carries the
    # value; the handle resolves the reference through its snapshot
    program = ASPProgram()
    F = Predicate.define("f_const", ["x"])
    n = program.define_constant("n_assume", 4)
    program.fact(Choice(F(x=RangePool(1, n))))
    grounded = program.ground()
    result = grounded.solve(models=0, assumptions=[F(x=n)])
    models = list(result)
    assert all(F(x=4) in set(m.atoms(F)) for m in models)
    assert len(models) == 8  # 2^3 for the other slots


def test_expression_assumptions_rejected_with_teaching() -> None:
    grounded = make_program().ground()
    with pytest.raises(ValueError, match="pass the computed value"):
        grounded.solve(assumptions=[A(value=Number(1) + 1)])


def test_assumption_rejection_names_the_inner_term() -> None:
    grounded = make_program().ground()
    X = Variable("X")
    with pytest.raises(TypeError, match="got ~Comparison"):
        grounded.solve(assumptions=[~(X == 3)])
