"""
Tests for the scoping machinery, pinned LIVE against gringo on every run:
ok() requires gringo to ground what validate_rule accepts (an over-strict
analysis would otherwise never be caught), and every bad() case declares
gringo's own verdict on the raw text — True pins the over-approximation
contract (a safety rejection is a certain gringo rejection), False records
a deliberate pyclingo-only rejection (the singleton lint, the
aggregate-tuple-sharing lint, teaching walls on meaningless spellings, and
the unbound-conditional-literal-head case, where gringo is laxer).
"""

from collections.abc import Sequence

import clingo
import pytest

from pyclingo import (
    ANY,
    ASPProgram,
    Choice,
    ConditionalLiteral,
    Count,
    Not,
    Predicate,
    Sum,
    Term,
    Variable,
)
from pyclingo.program_elements import render_body_terms
from pyclingo.scoping import validate_rule

P = Predicate.define("p", ["x"])
Q = Predicate.define("q", ["x"])
R2 = Predicate.define("r2", ["x", "y"])


def _gringo_grounds(head: Term | None, body: Sequence[Term]) -> bool:
    """
    Whether gringo itself grounds the rule (unsafe variables are ground-time
    errors). A never-true guard atom rides in the body: gringo's safety
    verdict is static and unaffected, but a self-recursive assignment
    aggregate (p(N) :- #count{ X : p(X) } = N) would otherwise grow its
    value set forever during grounding.
    """
    head_str = "" if head is None else head.render()
    guarded_body = f"{render_body_terms(list(body))}, __probe_guard" if body else "__probe_guard"
    control = clingo.Control(logger=lambda code, message: None)
    try:
        control.add("base", [], f"{head_str} :- {guarded_body}.")
        control.ground([("base", [])])
    except RuntimeError:
        return False
    return True


def _rule_text(head: Term | None, body: Sequence[Term]) -> str:
    head_str = "" if head is None else head.render()
    return f"{head_str} :- {render_body_terms(list(body))}." if body else f"{head_str}."


def ok(head: Term | None, body: Sequence[Term]) -> None:
    """Accepted by validate_rule AND grounded by gringo — the pin holds both ways, live."""
    validate_rule(head, list(body), "<test rule>")
    assert _gringo_grounds(head, body), f"pyclingo accepted a rule gringo rejects: {_rule_text(head, body)}"


def bad(head: Term | None, body: Sequence[Term], match: str, *, gringo_rejects: bool) -> None:
    """
    Rejected by validate_rule, with gringo's own verdict as the receipt:
    gringo_rejects=True pins the over-approximation contract; False records
    a deliberate pyclingo-only rejection of text gringo grounds.
    """
    with pytest.raises(ValueError, match=match):
        validate_rule(head, list(body), "<test rule>")
    if gringo_rejects:
        assert not _gringo_grounds(head, body), f"gringo accepts a rule we reject as unsafe: {_rule_text(head, body)}"
    else:
        assert _gringo_grounds(head, body), (
            f"gringo also rejects {_rule_text(head, body)}: mark this case gringo_rejects=True"
        )


X, Y, N = Variable("X"), Variable("Y"), Variable("N")


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
    bad(P(x=X), [Not(Q(x=X))], "Unsafe variable", gringo_rejects=True)


def test_non_equality_comparisons_do_not_bind() -> None:
    bad(P(x=X), [X != 5, Q(x=Y), Y == Y], "Unsafe variable", gringo_rejects=True)


def test_head_variable_never_in_body_is_unsafe() -> None:
    bad(P(x=X), [Q(x=Y), P(x=Y)], "Singleton|Unsafe", gringo_rejects=True)  # X unsafe (also singleton)


def test_comparison_head_variables_need_body_binding() -> None:
    ok(X == Y, [R2(x=X, y=Y)])  # comparison heads are valid, vars bound
    bad(X == Y, [Q(x=X), P(x=X)], "Unsafe variable", gringo_rejects=True)  # Y unbound


def test_cardinality_bound_variables_are_global() -> None:
    ok(
        Choice(P(x=X), condition=Q(x=X)).exactly(N),
        [R2(x=N, y=N)],
    )
    bad(Choice(P(x=X), condition=Q(x=X)).exactly(N), [Q(x=Y), P(x=Y)], "Unsafe variable", gringo_rejects=True)


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
    Cell, AnchorCell, Size = (Variable(n) for n in ("Cell", "AnchorCell", "Size"))
    Region = Predicate.define("region", ["loc", "anchor"])
    ok(
        R2(x=AnchorCell, y=Size),
        [
            Q(x=AnchorCell),
            Size == Count(Cell, condition=Region(loc=Cell, anchor=AnchorCell)),
        ],
    )


def test_aggregate_target_not_in_condition_is_a_local_safety_error() -> None:
    bad(P(x=N), [Q(x=N), N == Count(X, condition=P(x=Y))], "Unsafe local", gringo_rejects=True)


def test_choice_element_variable_without_condition_is_global() -> None:
    ok(Choice(P(x=X)), [Q(x=X), P(x=X)])  # bound by the body: fine
    bad(Choice(P(x=X)), [Q(x=Y), P(x=Y)], "Unsafe variable", gringo_rejects=True)  # nothing binds X


def test_choice_element_variable_bound_by_own_condition_is_local() -> None:
    ok(Choice(P(x=X), condition=Q(x=X)), [Q(x=Y), P(x=Y)])


def test_conditional_literal_head_var_not_in_condition_is_global() -> None:
    # gringo GROUNDS this text (an unbound conditional-literal head variable
    # is local to the literal); pyclingo rejects it anyway — the stricter
    # verdict is recorded here as deliberate
    bad(None, [ConditionalLiteral(P(x=X), Q(x=Y)), R2(x=Y, y=Y)], "Unsafe|Singleton", gringo_rejects=False)
    ok(None, [ConditionalLiteral(P(x=X), Q(x=X)), Not(P(x=1))])


# --- anonymous variable ---


def test_anonymous_in_head_is_rejected() -> None:
    bad(P(x=ANY), [Q(x=1)], "anonymous", gringo_rejects=True)


def test_anonymous_in_body_needs_nothing() -> None:
    ok(P(x=1), [Q(x=ANY)])


# --- singletons ---


def test_singleton_variable_is_rejected() -> None:
    bad(P(x=1), [Q(x=X)], "Singleton", gringo_rejects=False)  # gringo is silent about singletons


def test_singleton_local_is_rejected() -> None:
    bad(P(x=1), [Count(X, condition=P(x=Y)) == 1], "Singleton|Unsafe", gringo_rejects=True)


def test_two_uses_is_not_a_singleton() -> None:
    ok(P(x=X), [Q(x=X)])


# --- global variables in aggregate tuples (valid clingo, collapsed semantics) ---


def test_global_variable_in_aggregate_tuple_is_rejected() -> None:
    # X fixed by the rule makes {X : p(X)} contain at most one element
    bad(Q(x=X), [Q(x=X), Count(X, condition=P(x=X)) == 1], "collapses", gringo_rejects=False)


def test_global_in_sum_tuple_is_rejected_even_mixed_with_locals() -> None:
    W = Variable("W")
    bad(Q(x=X), [Q(x=X), Sum((W, X), condition=R2(x=W, y=X)) == 1], "collapses", gringo_rejects=False)


def test_global_in_aggregate_condition_stays_legal() -> None:
    # The per-anchor pattern: aggregation parameterized by a global is fine
    Cell, AnchorCell, Size = (Variable(n) for n in ("Cell", "AnchorCell", "Size"))
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
    # not #count{ C : q(C) } > 3 — C is the aggregate's local, not an unsafe
    # global; clingo accepts this rule silently
    C = Variable("C")
    ok(P(x=1), [Q(x=1), Not(Count(C, condition=Q(x=C)) > 3)])


def test_negated_equality_does_not_bind() -> None:
    bad(P(x=X), [Q(x=Y), P(x=Y), Not(X == Y + 1)], "Unsafe variable", gringo_rejects=True)


# --- occurrence counting within one literal ---


def test_variable_twice_in_one_literal_is_not_a_singleton() -> None:
    # forbid reflexive pairs: X occurs twice in edge(X, X)
    ok(None, [R2(x=X, y=X)])


def test_repeated_variable_in_expression_arguments_counts() -> None:
    ok(P(x=X + X), [Q(x=X)])


# --- the singleton lint is program-switchable; safety is not ---


def test_allow_singletons_switches_off_the_lint() -> None:
    program = ASPProgram(allow_singletons=True)
    program.when(Q(x=X)).derive(P(x=1))  # X used once: fine here
    assert "p(1) :- q(X)." in program.render()


def test_allow_singletons_does_not_soften_safety() -> None:
    program = ASPProgram(allow_singletons=True)
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.when(Q(x=Y)).derive(P(x=X))


# --- occurrence counting recurses into local Comparison conditions ---


def test_negated_comparison_local_condition_counts_variables() -> None:
    # The Not(X == Y) local condition drives _occurrences through its inner
    # Comparison, counting X and Y on each non-aggregate side
    ok(
        P(x=N),
        [Q(x=N), N == Count(X, condition=[R2(x=X, y=Y), Not(X == Y)])],
    )


# --- empty-left equality edge binds its unbound right side ---


def test_assignment_aggregate_on_left_binds_right_alone() -> None:
    # Count(...) == N puts the aggregate (all-local) on the left, leaving an
    # empty-left edge (frozenset(), {N}) that binds N unconditionally.
    # N is bound ONLY by this edge (mirrors clingo p(N) :- #count{X:p(X)} = N.)
    ok(P(x=N), [Count(X, condition=P(x=X)) == N])


# --- equality edge from a non-pool equality inside a construct element ---


def test_local_equality_edge_binds_aggregate_target() -> None:
    # Q(x=Y) binds Y inside the element; the X == Y local equality edge then
    # binds the target X (line 216 records that edge)
    ok(P(x=N), [Q(x=N), N == Count(X, condition=[Q(x=Y), X == Y])])


# --- anonymous variable in a comparison head ---


def test_anonymous_in_comparison_head_is_rejected() -> None:
    bad(X == ANY, [Q(x=X)], "anonymous", gringo_rejects=True)


# --- anonymous variable in a choice element target ---


def test_anonymous_in_choice_head_is_rejected() -> None:
    bad(Choice(P(x=ANY)), [Q(x=1)], "anonymous", gringo_rejects=True)


# --- optimization singleton lint is switchable ---


def test_optimization_singleton_lint_off_under_allow_singletons() -> None:
    program = ASPProgram(allow_singletons=True)
    Pair = Predicate.define("pair", ["a", "b"])
    program.minimize(X, condition=Pair(a=X, b=Y))  # Y singleton, lint disabled
    assert "#minimize" in program.render()


def test_unsafe_rules_raise_at_the_statement_verb() -> None:
    # The program-level door: rejection lands at the when() call, on the
    # author's own line, not at clingo's grounding error
    program = ASPProgram()
    X, Y = Variable("X"), Variable("Y")
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.when(P(x=X)).derive(Q(x=Y))
