"""
Tests for ASPProgram.recursion_profile()/analyze_recursion(): the
recursive components of the predicate dependency graph, with the
statements grounding inside each component's fixpoint. Static analysis —
no grounding is performed.
"""

import pytest

from aspalchemy import ANY, ASPProgram, Choice, ConditionalLiteral, Count, Predicate, RangePool, Variable

E = Predicate.define("e_rp", ["a", "b"])
Tc = Predicate.define("tc_rp", ["a", "b"])


def build_transitive_closure() -> ASPProgram:
    program = ASPProgram()
    X, Y, Z = Variable("X"), Variable("Y"), Variable("Z")
    program.fact(E(a=1, b=2), E(a=2, b=3))
    program.when(E(a=X, b=Y)).derive(Tc(a=X, b=Y))
    program.when(Tc(a=X, b=Y), E(a=Y, b=Z)).derive(Tc(a=X, b=Z))
    return program


def test_self_loop_component_lists_only_fixpoint_statements() -> None:
    profile = build_transitive_closure().recursion_profile()
    assert len(profile) == 1
    component = profile[0]
    assert component.signatures == (("tc_rp", 2),)
    assert not component.unstratified
    # The base rule seeds the component but has no body dependency inside
    # it, so only the recursive rule grounds within the fixpoint
    statements = [statement for statement, _location in component.statements]
    assert statements == ["tc_rp(X, Z) :- tc_rp(X, Y), e_rp(Y, Z)."]
    assert component.statements[0][1] is not None
    assert component.statements[0][1].filename.endswith("test_recursion_profile.py")


def test_derive_merges_the_component_and_require_does_not() -> None:
    # The Galaxies finding, distilled: deriving the connection from the
    # region places the three-way join inside the recursive component;
    # requiring it instead leaves the recursion a self-loop
    Conn = Predicate.define("conn_rp", ["a", "b"])
    Reg = Predicate.define("reg_rp", ["a"])
    X, Y = Variable("X"), Variable("Y")

    def base(derive_connection: bool) -> ASPProgram:
        program = ASPProgram()
        program.fact(Reg(a=1))
        program.choose(Choice(Conn(a=RangePool(1, 3), b=RangePool(1, 3))))
        program.when(Conn(a=X, b=Y), Reg(a=X)).derive(Reg(a=Y))
        if derive_connection:
            program.when(Reg(a=X), Reg(a=Y)).derive(Conn(a=X, b=Y))
        else:
            program.when(Reg(a=X), Reg(a=Y)).require(Conn(a=X, b=Y))
        return program

    derived = base(derive_connection=True).recursion_profile()
    assert len(derived) == 1
    assert derived[0].signatures == (("conn_rp", 2), ("reg_rp", 1))
    assert len(derived[0].statements) == 2  # propagation AND the join both in the fixpoint

    required = base(derive_connection=False).recursion_profile()
    assert len(required) == 1
    assert required[0].signatures == (("reg_rp", 1),)
    assert len(required[0].statements) == 1  # the requirement has no head: out of the fixpoint


def test_unstratified_component_is_flagged() -> None:
    P = Predicate.define("p_us", ["x"])
    Q = Predicate.define("q_us", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(P(x=1))
    program.when(P(x=X)).derive(Q(x=X))
    program.when(Q(x=X)).derive(P(x=X))
    program.when(Q(x=X), ~P(x=X)).derive(P(x=X))
    profile = program.recursion_profile()
    assert len(profile) == 1
    assert profile[0].unstratified
    assert "UNSTRATIFIED" in program.analyze_recursion()


def test_choice_head_targets_are_heads_and_conditions_are_dependencies() -> None:
    P = Predicate.define("p_ch", ["x"])
    Q = Predicate.define("q_ch", ["x"])
    R = Predicate.define("r_ch", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(R(x=RangePool(1, 3)))
    program.when(R(x=X)).choose(Choice(P(x=X), condition=Q(x=X)))
    program.when(P(x=X)).derive(Q(x=X))
    profile = program.recursion_profile()
    assert len(profile) == 1
    assert profile[0].signatures == (("p_ch", 1), ("q_ch", 1))
    assert not any("r_ch" in f"{name}" for name, _arity in profile[0].signatures)


def test_aggregate_bodies_carry_dependencies() -> None:
    S = Predicate.define("s_ag", ["n"])
    T = Predicate.define("t_ag", ["n"])
    program = ASPProgram()
    X, N = Variable("X"), Variable("N")
    program.fact(T(n=1))
    program.when(N == Count(X, condition=T(n=X))).derive(S(n=N))
    program.when(S(n=X)).derive(T(n=X))
    profile = program.recursion_profile()
    assert len(profile) == 1
    assert profile[0].signatures == (("s_ag", 1), ("t_ag", 1))


def test_no_recursion_is_empty_and_prose_says_so() -> None:
    P = Predicate.define("p_nr", ["x"])
    Q = Predicate.define("q_nr", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(P(x=RangePool(1, 3)))
    program.when(P(x=X)).derive(Q(x=X))
    assert program.recursion_profile() == ()
    assert program.analyze_recursion() == "Recursion profile: no recursive components"


def test_predicates_as_arguments_are_not_dependencies() -> None:
    Wrap = Predicate.define("wrap_rp", ["inner"])
    Item = Predicate.define("item_rp", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(Item(x=1))
    program.when(Item(x=X)).derive(Wrap(inner=Item(x=X)))  # Item as a TERM argument
    assert program.recursion_profile() == ()


def test_negation_only_cycles_are_reported_unstratified() -> None:
    # The textbook unstratified shape: p and q defined by each other's
    # absence. Not a grounding fixpoint, but a component whose cycle
    # passes entirely through negation — reported and flagged.
    P = Predicate.define("p_no", ["x"])
    Q = Predicate.define("q_no", ["x"])
    D = Predicate.define("d_no", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(D(x=RangePool(1, 2)))
    program.when(D(x=X), ~Q(x=X)).derive(P(x=X))
    program.when(D(x=X), ~P(x=X)).derive(Q(x=X))
    profile = program.recursion_profile()
    assert len(profile) == 1
    assert profile[0].signatures == (("p_no", 1), ("q_no", 1))
    assert profile[0].unstratified
    assert len(profile[0].statements) == 2  # both negation carriers listed


def test_self_negation_is_a_reportable_singleton() -> None:
    P = Predicate.define("p_sn", ["x"])
    D = Predicate.define("d_sn", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(D(x=1))
    program.when(D(x=X), ~P(x=X)).derive(P(x=X))
    profile = program.recursion_profile()
    assert len(profile) == 1
    assert profile[0].signatures == (("p_sn", 1),)
    assert profile[0].unstratified


def test_negation_merges_positive_components_into_one_unstratified() -> None:
    # Two positive fixpoints joined by mutual negation ground/solve
    # entangled: one component of four signatures, flagged
    A = Predicate.define("a_mg", ["x"])
    B = Predicate.define("b_mg", ["x"])
    S = Predicate.define("s_mg", ["x"])
    T = Predicate.define("t_mg", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(A(x=1), S(x=1))
    program.when(A(x=X)).derive(B(x=X))
    program.when(B(x=X)).derive(A(x=X))
    program.when(S(x=X)).derive(T(x=X))
    program.when(T(x=X)).derive(S(x=X))
    program.when(~S(x=X), B(x=X)).derive(A(x=X))
    program.when(~A(x=X), T(x=X)).derive(S(x=X))
    profile = program.recursion_profile()
    assert len(profile) == 1
    assert len(profile[0].signatures) == 4
    assert profile[0].unstratified


def test_prose_format_and_truncation() -> None:
    Long = Predicate.define("very_long_predicate_name_for_truncation_rp", ["a", "b", "c", "d"])
    program = ASPProgram()
    A, B, C, D = Variable("A"), Variable("B"), Variable("C"), Variable("D")
    program.fact(Long(1, 1, 1, 1))
    program.when(Long(A, B, C, D), Long(B, A, D, C), ANY == ANY if False else Long(C, D, A, B)).derive(Long(D, C, B, A))
    prose = program.analyze_recursion()
    lines = prose.splitlines()
    assert lines[0] == "Recursion profile: 1 recursive component"
    assert "very_long_predicate_name_for_truncation_rp/4" in lines[1]
    assert any(line.rstrip().endswith("...") or "..." in line for line in lines[2:])


def test_locations_off_reads_unknown() -> None:
    P = Predicate.define("p_rl", ["x"])
    program = ASPProgram(source_locations=False)
    X = Variable("X")
    program.fact(P(x=1))
    program.when(P(x=X)).derive(P(x=X))
    assert "unknown (source locations off)" in program.analyze_recursion()


def test_conditional_literal_bodies_carry_dependencies() -> None:
    # A body conditional literal's head and condition are both
    # dependencies of the rule's head
    A = Predicate.define("a_cl2", ["x"])
    B = Predicate.define("b_cl2", ["x"])
    C = Predicate.define("c_cl2", ["x"])
    program = ASPProgram()
    X, Y = Variable("X"), Variable("Y")
    program.fact(C(x=RangePool(1, 2)))
    program.when(C(x=X), ConditionalLiteral(B(x=Y), C(x=Y))).derive(A(x=X))
    program.when(A(x=X)).derive(B(x=X))
    profile = program.recursion_profile()
    assert len(profile) == 1
    assert profile[0].signatures == (("a_cl2", 1), ("b_cl2", 1))


def test_comparison_heads_derive_nothing() -> None:
    # 'X = Y :- condition(X), condition(Y).' is legal gringo and derives no
    # atoms: a comparison head must contribute no head signatures (pinned
    # because the walker's dispatch order is what guarantees it)
    Cond = Predicate.define("condition_ch", ["x"])
    X, Y = Variable("X"), Variable("Y")
    for spell_as_require in (True, False):
        program = ASPProgram()
        program.fact(Cond(x=RangePool(1, 3)))
        pending = program.when(Cond(x=X), Cond(x=Y))
        if spell_as_require:
            pending.require(X == Y)
        else:
            pending.derive(X == Y)
        assert program.recursion_profile() == ()


def test_classical_negation_signs_are_distinct_nodes() -> None:
    # Audit regression: merging p/1 and -p/1 fabricated a component that
    # gringo grounds bottom-up (Tight: Yes). Signs are distinct nodes.
    P = Predicate.define("p_sgn", ["x"])
    Q = Predicate.define("q_sgn", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(-P(x=1))
    program.when(Q(x=X)).derive(P(x=X))
    program.when(-P(x=X)).derive(Q(x=X))
    assert program.recursion_profile() == ()
    # Genuine recursion on the NEGATIVE sign is still seen
    E = Predicate.define("e_sgn", ["a", "b"])
    program2 = ASPProgram()
    X, Y = Variable("X"), Variable("Y")
    program2.fact(E(a=1, b=2), -P(x=1))
    program2.when(-P(x=X), E(a=X, b=Y)).derive(-P(x=Y))
    profile = program2.recursion_profile()
    assert len(profile) == 1
    assert profile[0].signatures == (("-p_sgn", 1),)


def test_compound_comparison_operands_are_not_dependencies() -> None:
    # Audit regression: 'W == q(X)' is a destructuring term equation, not
    # an atom occurrence — it must not fabricate a self-loop
    Q = Predicate.define("q_dq", ["x"])
    D = Predicate.define("d_dq", ["x"])
    program = ASPProgram()
    X, W = Variable("X"), Variable("W")
    program.fact(D(x=RangePool(1, 2)))
    program.when(D(x=X), W == Q(x=X)).derive(Q(x=W))
    assert program.recursion_profile() == ()


def test_open_when_is_refused() -> None:
    # A pending when() would silently truncate the analysis; refuse it the
    # way render() does
    P = Predicate.define("p_ow", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(P(x=1))
    pending = program.when(P(x=X))
    with pytest.raises(ValueError, match="incomplete when"):
        program.recursion_profile()
    pending.derive(P(x=X))  # complete it; the profile now answers
    assert len(program.recursion_profile()) == 1
