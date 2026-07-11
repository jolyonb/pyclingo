"""
Tests for Choice construction guards.
"""

import inspect
import re

import clingo
import pytest

from pyclingo import ANY, SUP, ASPProgram, Choice, Count, Not, Number, Predicate, SourceLocation, String, Variable


def test_impossible_cardinality_rejected() -> None:
    # Statically impossible bounds would render fine but be silently UNSAT
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match="impossible"):
        Choice(P(x=1)).at_least(3).at_most(2)
    with pytest.raises(ValueError, match="impossible"):
        Choice(P(x=1)).at_most(2).at_least(3)
    Choice(P(x=1)).at_least(2).at_most(3)  # possible bounds fine
    Choice(P(x=1)).at_least(Variable("N")).at_most(2)  # variable bounds skipped


def test_aggregates_rejected_in_conditions() -> None:
    # clingo cannot parse an aggregate inside a choice condition
    P = Predicate.define("p", ["x"])
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="inside choice conditions"):
        Choice(P(x=X), condition=Count(Y, condition=P(x=Y)) > 0)
    with pytest.raises(ValueError, match="inside choice conditions"):
        Choice(P(x=X), condition=[P(x=X), Count(Y, condition=P(x=Y)) > 0])


def test_choice_freezes_when_captured_by_a_rule() -> None:
    program = ASPProgram()
    P, Q = Predicate.define("p", ["x"]), Predicate.define("q", ["x"])
    X = Variable("X")
    choice = Choice(P(x=X), condition=Q(x=X))
    program.when(Q(x=X)).derive(choice)
    with pytest.raises(RuntimeError, match="frozen"):
        choice.add(P(x=X))
    with pytest.raises(RuntimeError, match="frozen"):
        choice.at_most(3)


def test_choice_builds_freely_before_capture_and_shares_after() -> None:
    program = ASPProgram()
    P, Q, R = (Predicate.define(n, ["x"]) for n in ("p", "q", "r"))
    X = Variable("X")
    choice = Choice(P(x=X), condition=Q(x=X)).add(R(x=X)).exactly(1)  # chaining pre-capture
    program.when(Q(x=X)).derive(choice)
    program.when(R(x=X)).derive(choice)  # a frozen choice is a value: same choice under a second body
    assert program.render().count("{ p(X) : q(X); r(X) } = 1") == 2


def test_shared_choice_rules_each_report_their_own_line() -> None:
    # Sharing puts one builder under two rules; locations live on the rules,
    # so each reports the line of ITS derive
    program = ASPProgram()
    P, Q, R = (Predicate.define(n, ["x"]) for n in ("p_sl", "q_sl", "r_sl"))
    X = Variable("X")
    choice = Choice(P(x=X), condition=Q(x=X))
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    program.when(Q(x=X)).derive(choice)  # lineno + 1
    program.when(R(x=X)).derive(choice)  # lineno + 2
    first, second = program["Rules"]
    assert first.source_location == SourceLocation(frame.f_code.co_filename, lineno + 1)
    assert second.source_location == SourceLocation(frame.f_code.co_filename, lineno + 2)


def test_frozen_choice_error_names_the_capturing_line() -> None:
    program = ASPProgram()
    P, Q = Predicate.define("p_rc", ["x"]), Predicate.define("q_rc", ["x"])
    X = Variable("X")
    choice = Choice(P(x=X), condition=Q(x=X))
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    program.when(Q(x=X)).derive(choice)  # lineno + 1
    where = SourceLocation(frame.f_code.co_filename, lineno + 1).display()
    with pytest.raises(RuntimeError, match=re.escape(f"captured by the rule at {where}")):
        choice.add(P(x=X))


def test_frozen_choice_error_without_receipt_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # When capture found no user frame, the error keeps its unlocated wording
    monkeypatch.setattr("pyclingo.conditioned_element.capture_location", lambda: None)
    program = ASPProgram()
    P = Predicate.define("p_nr", ["x"])
    choice = Choice(P(x=1))
    program.choose(choice)
    with pytest.raises(RuntimeError, match="captured by a rule and is frozen"):
        choice.at_most(1)


def test_negative_cardinality_rejected_for_number_too() -> None:
    # The int path and the Number path validate identically
    P = Predicate.define("p9", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match="non-negative"):
        Choice(P(x=X)).exactly(-1)
    with pytest.raises(ValueError, match="non-negative"):
        Choice(P(x=X)).exactly(Number(-1))
    # The literal spelling -Number(1): the one Expression shape the guard
    # folds (general expressions are not evaluated — gringo owns those)
    with pytest.raises(ValueError, match="non-negative"):
        Choice(P(x=X)).at_most(-Number(1))


def test_negation_wrapped_aggregate_condition_rejected() -> None:
    # Not(...) wrapping must not smuggle an aggregate past the guard
    P = Predicate.define("p10", ["x"])
    Q = Predicate.define("q10", ["x"])
    X, C = Variable("X"), Variable("C")
    with pytest.raises(ValueError, match="separate rule"):
        Choice(P(x=X), condition=Not(Count(C, condition=Q(x=C)) > 3))


def test_expression_cardinality_bounds() -> None:
    # { pick(X) : c(X) } = N + 1 :- size(N).  — gringo-legal, probed
    program = ASPProgram()
    Size = Predicate.define("size", ["n"], show=False)
    C = Predicate.define("c", ["x"], show=False)
    Pick = Predicate.define("pick", ["x"])
    N, X = Variable("N"), Variable("X")
    program.fact(Size(n=2), *[C(x=i) for i in range(1, 5)])
    program.when(Size(n=N)).derive(Choice(Pick(x=X), condition=C(x=X)).exactly(N + 1))
    models = list(program.solve())
    assert len(models) == 4  # C(4, 3) ways to pick 3 of 4
    assert all(len(m.atoms(Pick)) == 3 for m in models)


def test_expression_bound_variables_must_bind() -> None:
    # The bound's variables are global: unbound ones are rejected
    program = ASPProgram()
    P = Predicate.define("p_eb", ["x"])
    Q = Predicate.define("q_eb", ["x"])
    N, X = Variable("N"), Variable("X")
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.when(Q(x=1)).derive(Choice(P(x=X), condition=Q(x=X)).exactly(N + 1))


def test_non_predicate_element_rejected() -> None:
    # Both the constructor and add() route the element through the same guard
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="must be a Predicate"):
        Choice(5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be a Predicate"):
        Choice(P(x=1)).add("nope")  # type: ignore[arg-type]


def test_cardinality_bad_type_rejected() -> None:
    # A float is neither int, Value, nor Expression
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="integer, Value, or Expression"):
        Choice(P(x=1)).exactly(2.5)  # type: ignore[arg-type]


def test_cardinality_string_rejected() -> None:
    # A String is a Value so it slips past the type check and is caught explicitly
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="cannot be a String"):
        Choice(P(x=1)).exactly(String("three"))


def test_cardinality_extreme_value_rejected() -> None:
    # SUP/INF are Values too; a cardinality bound is integer-valued
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="must be integer-valued, got #sup"):
        Choice(P(x=1)).at_most(SUP)


def test_exactly_after_bound_already_set_rejected() -> None:
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match="already set"):
        Choice(P(x=1)).at_least(1).exactly(2)
    with pytest.raises(ValueError, match="already set"):
        Choice(P(x=1)).exactly(1).exactly(2)


def test_at_least_already_set_rejected() -> None:
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match="Minimum cardinality is already set"):
        Choice(P(x=1)).at_least(1).at_least(2)


def test_at_most_already_set_rejected() -> None:
    P = Predicate.define("p", ["x"])
    with pytest.raises(ValueError, match="Maximum cardinality is already set"):
        Choice(P(x=1)).at_most(3).at_most(4)


def test_is_grounded_ungrounded_element() -> None:
    P = Predicate.define("p", ["x"])
    X = Variable("X")
    assert Choice(P(x=X)).is_grounded is False
    assert Choice(P(x=1)).exactly(2).is_grounded is True


def test_is_grounded_ungrounded_min_bound() -> None:
    P = Predicate.define("p", ["x"])
    N = Variable("N")
    assert Choice(P(x=1)).at_least(N).is_grounded is False


def test_is_grounded_ungrounded_max_bound() -> None:
    P = Predicate.define("p", ["x"])
    M = Variable("M")
    assert Choice(P(x=1)).at_most(M).is_grounded is False


def test_str_and_repr() -> None:
    P = Predicate.define("p", ["x"])
    X = Variable("X")
    choice = Choice(P(x=X))
    assert str(choice) == choice.render() == "{ p(X) }"
    assert repr(choice) == "Choice('{ p(X) }')"


def test_collect_variables_gathers_elements_and_bounds() -> None:
    P = Predicate.define("p", ["x"])
    X, N, M = Variable("X"), Variable("N"), Variable("M")
    choice = Choice(P(x=X)).at_least(N).at_most(M)
    assert choice.collect_variables() == {"X", "N", "M"}


def test_non_condition_type_rejected() -> None:
    # A raw int trips the isinstance guard in ConditionedElement
    P = Predicate.define("p", ["x"])
    with pytest.raises(TypeError, match="must be a Predicate, DefaultNegation, or Comparison"):
        Choice(P(x=1), condition=5)  # type: ignore[arg-type]


def test_conditioned_element_is_grounded() -> None:
    P = Predicate.define("p", ["x"])
    assert Choice(P(x=1)).is_grounded is True
    assert Choice(P(x=Variable("X"))).is_grounded is False


def test_conditioned_element_collect_variables_targets_and_conditions() -> None:
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"])
    X, Y = Variable("X"), Variable("Y")
    assert Choice(P(x=X), condition=Q(x=Y)).collect_variables() == {"X", "Y"}


def test_when_choose_is_the_conditional_choice_spelling() -> None:
    # when(...).choose(c) and when(...).derive(c) are one statement; the
    # verb names it, as require does for forbid
    P = Predicate.define("p_wc", ["x"])
    Q = Predicate.define("q_wc", ["x"])
    X = Variable("X")
    named = ASPProgram()
    named.when(Q(x=X)).choose(Choice(P(x=X)).exactly(1))
    general = ASPProgram()
    general.when(Q(x=X)).derive(Choice(P(x=X)).exactly(1))
    assert named.render() == general.render()
    with pytest.raises(TypeError, match=r"choose\(\) takes a Choice, got p_wc.*\.derive\(\)"):
        ASPProgram().when(Q(x=1)).choose(P(x=1))  # type: ignore[arg-type]


def test_anonymous_cardinality_bound_rejected_with_receipt() -> None:
    # '_' as a bound binds nothing: certain gringo rejection ('#Anon0' is
    # unsafe), rejected at construction with the author's line
    P = Predicate.define("p_anon_card", ["x"])
    Q = Predicate.define("q_anon_card", ["x"])
    X = Variable("X")
    with pytest.raises(ValueError, match="cannot be '_'"):
        Choice(P(x=X), condition=Q(x=X)).at_most(ANY)
    # gringo's live verdict on the equivalent text
    receipt = clingo.Control(logger=lambda code, message: None)
    receipt.add("base", [], "q_anon_card(1). { p_anon_card(X) : q_anon_card(X) } _.")
    with pytest.raises(RuntimeError):
        receipt.ground([("base", [])])
