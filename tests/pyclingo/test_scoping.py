"""
Tests for the scoping machinery: one test per empirically probed gringo
binding rule (see VALIDATION.md section 0). These pin the ground truth the
unsafe/singleton validation stands on.
"""

from collections.abc import Sequence

import pytest

from pyclingo import ANY, Choice, ConditionalLiteral, Count, Not, Predicate, Sum, Term, Variable, create_variables
from pyclingo.scoping import validate_rule

P = Predicate.define("p", ["x"])
Q = Predicate.define("q", ["x"])
R2 = Predicate.define("r2", ["x", "y"])


def ok(head: Term | None, body: Sequence[Term]) -> None:
    validate_rule(head, list(body), "<test rule>")


def bad(head: Term | None, body: Sequence[Term], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        validate_rule(head, list(body), "<test rule>")


X, Y, N = create_variables("X", "Y", "N")


# --- binding through equality ---


def test_equality_with_bound_side_binds_the_other() -> None:
    ok(P(x=X), [Q(x=Y), X == Y + 1])  # Y bound positively; X via equality
    ok(P(x=X), [Q(x=Y), Y + 1 == X])  # either orientation


def test_equality_chains_resolve_as_fixpoint() -> None:
    Z = Variable("Z")
    # X depends on Y, Y depends on Z, Z bound — order independent
    ok(P(x=X), [X == Y + 1, Y == Z + 1, Q(x=Z)])


def test_pool_assignment_binds() -> None:
    ok(P(x=X), [X.in_([1, 3]), Q(x=X)])
    ok(P(x=X), [X.in_(range(1, 4)), Q(x=X)])


def test_aggregate_equality_binds() -> None:
    ok(P(x=N), [Q(x=N), N == Count(X, condition=P(x=X))])
    ok(P(x=N), [Q(x=N), Count(X, condition=P(x=X)) == N])


# --- things that do NOT bind ---


def test_negated_literals_do_not_bind() -> None:
    bad(P(x=X), [Not(Q(x=X))], "Unsafe variable")


def test_non_equality_comparisons_do_not_bind() -> None:
    bad(P(x=X), [X != 5, Q(x=Y), Y == Y], "Unsafe variable")


def test_head_variable_never_in_body_is_unsafe() -> None:
    bad(P(x=X), [Q(x=Y), P(x=Y)], "Singleton|Unsafe")  # X unsafe (also singleton)


def test_comparison_head_variables_need_body_binding() -> None:
    ok(X == Y, [R2(x=X, y=Y)])  # comparison heads are valid, vars bound
    bad(X == Y, [Q(x=X), P(x=X)], "Unsafe variable")  # Y unbound


def test_cardinality_bound_variables_are_global() -> None:
    ok(
        Choice(P(x=X), condition=Q(x=X)).exactly(N),
        [R2(x=N, y=N)],
    )
    bad(Choice(P(x=X), condition=Q(x=X)).exactly(N), [Q(x=Y), P(x=Y)], "Unsafe variable")


# --- local scopes ---


def test_aggregate_locals_are_independent_of_globals() -> None:
    # X inside the aggregate is local; the rule-level X is a different variable
    ok(P(x=N), [Q(x=N), N == Count(X, condition=P(x=X))])


def test_same_local_name_in_two_constructs_is_independent() -> None:
    ok(
        P(x=N),
        [Q(x=N), N == Count(X, condition=P(x=X)), Count(X, condition=Q(x=X)) == N],
    )


def test_global_variable_inside_construct_counts_globally() -> None:
    # The regionconstructor pattern: Cell local, AnchorCell global
    Cell, AnchorCell, Size = create_variables("Cell", "AnchorCell", "Size")
    Region = Predicate.define("region", ["loc", "anchor"])
    ok(
        R2(x=AnchorCell, y=Size),
        [
            Q(x=AnchorCell),
            Size == Count(Cell, condition=Region(loc=Cell, anchor=AnchorCell)),
        ],
    )


def test_aggregate_target_not_in_condition_is_a_local_safety_error() -> None:
    bad(P(x=N), [Q(x=N), N == Count(X, condition=P(x=Y))], "Unsafe local")


def test_choice_element_variable_without_condition_is_global() -> None:
    ok(Choice(P(x=X)), [Q(x=X), P(x=X)])  # bound by the body: fine
    bad(Choice(P(x=X)), [Q(x=Y), P(x=Y)], "Unsafe variable")  # nothing binds X


def test_choice_element_variable_bound_by_own_condition_is_local() -> None:
    ok(Choice(P(x=X), condition=Q(x=X)), [Q(x=Y), P(x=Y)])


def test_conditional_literal_head_var_not_in_condition_is_global() -> None:
    bad(None, [ConditionalLiteral(P(x=X), Q(x=Y)), R2(x=Y, y=Y)], "Unsafe|Singleton")
    ok(None, [ConditionalLiteral(P(x=X), Q(x=X)), Not(P(x=1))])


# --- anonymous variable ---


def test_anonymous_in_head_is_rejected() -> None:
    bad(P(x=ANY), [Q(x=1)], "anonymous")


def test_anonymous_in_body_needs_nothing() -> None:
    ok(P(x=1), [Q(x=ANY)])


# --- singletons ---


def test_singleton_variable_is_rejected() -> None:
    bad(P(x=1), [Q(x=X)], "Singleton")


def test_singleton_local_is_rejected() -> None:
    bad(P(x=1), [Count(X, condition=P(x=Y)) == 1], "Singleton|Unsafe")


def test_two_uses_is_not_a_singleton() -> None:
    ok(P(x=X), [Q(x=X)])


# --- global variables in aggregate tuples (valid clingo, collapsed semantics) ---


def test_global_variable_in_aggregate_tuple_is_rejected() -> None:
    # X fixed by the rule makes {X : p(X)} contain at most one element
    bad(Q(x=X), [Q(x=X), Count(X, condition=P(x=X)) == 1], "collapses")


def test_global_in_sum_tuple_is_rejected_even_mixed_with_locals() -> None:
    W = Variable("W")
    bad(Q(x=X), [Q(x=X), Sum((W, X), condition=R2(x=W, y=X)) == 1], "collapses")


def test_global_in_aggregate_condition_stays_legal() -> None:
    # The per-anchor pattern: aggregation parameterized by a global is fine
    Cell, AnchorCell, Size = create_variables("Cell", "AnchorCell", "Size")
    Region = Predicate.define("region2", ["loc", "anchor"])
    ok(
        R2(x=AnchorCell, y=Size),
        [Q(x=AnchorCell), Size == Count(Cell, condition=Region(loc=Cell, anchor=AnchorCell))],
    )


def test_choice_element_sharing_a_global_stays_legal() -> None:
    # {p(X)} :- q(X) is meaningful: a choice about each bound X
    ok(Choice(P(x=X)), [Q(x=X)])


# --- negated literals: no binding, but no flattening either ---


def test_negated_aggregate_comparison_is_valid() -> None:
    # not #count{C : q(C)} > 3 — C is the aggregate's local, not an unsafe
    # global; clingo accepts this rule silently
    C = Variable("C")
    ok(P(x=1), [Q(x=1), Not(Count(C, condition=Q(x=C)) > 3)])


def test_negated_equality_does_not_bind() -> None:
    bad(P(x=X), [Q(x=Y), P(x=Y), Not(X == Y + 1)], "Unsafe variable")


# --- occurrence counting within one literal ---


def test_variable_twice_in_one_literal_is_not_a_singleton() -> None:
    # forbid reflexive pairs: X occurs twice in edge(X, X)
    ok(None, [R2(x=X, y=X)])


def test_repeated_variable_in_expression_arguments_counts() -> None:
    ok(P(x=X + X), [Q(x=X)])
