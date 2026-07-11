"""
Tests for variable RangePool bounds (X = 1..N): every behavior probed
against gringo before implementation. Ranges never invert — a variable
bound must be positively bound elsewhere; the scoping analysis models the
binding as a one-way edge (bounds -> left variable).
"""

import pytest

from aspalchemy import ANY, ASPProgram, Count, Predicate, RangePool, String, Variable

Size = Predicate.define("size", ["n"], show=False)
Q = Predicate.define("q", ["x"])


def test_binding_position_solves() -> None:
    # q(X) :- size(N), X = 1..N.  (probed: q(1), q(2), q(3))
    program = ASPProgram()
    N, X = Variable("N"), Variable("X")
    program.fact(Size(n=3))
    program.when(Size(n=N), X.in_(RangePool(1, N))).derive(Q(x=X))
    model = next(iter(program.solve()))
    assert sorted(a["x"].value for a in model.atoms(Q)) == [1, 2, 3]


def test_argument_position_head_expands() -> None:
    # p(1..N) :- size(N).  (probed: expands in the head)
    program = ASPProgram()
    N = Variable("N")
    program.fact(Size(n=3))
    program.when(Size(n=N)).derive(Q(x=RangePool(1, N)))
    model = next(iter(program.solve()))
    assert sorted(a["x"].value for a in model.atoms(Q)) == [1, 2, 3]


def test_expression_bounds_solve() -> None:
    # X = 1..N*2  (probed)
    program = ASPProgram()
    N, X = Variable("N"), Variable("X")
    program.fact(Size(n=2))
    program.when(Size(n=N), X.in_(RangePool(1, N * 2))).derive(Q(x=X))
    model = next(iter(program.solve()))
    assert sorted(a["x"].value for a in model.atoms(Q)) == [1, 2, 3, 4]


def test_both_bounds_variables_solve() -> None:
    # X = L..H  (probed)
    Lo = Predicate.define("lo", ["n"], show=False)
    Hi = Predicate.define("hi", ["n"], show=False)
    program = ASPProgram()
    L, H, X = Variable("L"), Variable("H"), Variable("X")
    program.fact(Lo(n=2), Hi(n=4))
    program.when(Lo(n=L), Hi(n=H), X.in_(RangePool(L, H))).derive(Q(x=X))
    model = next(iter(program.solve()))
    assert sorted(a["x"].value for a in model.atoms(Q)) == [2, 3, 4]


def test_runtime_empty_range_is_not_an_error() -> None:
    # lo(5)..hi(2): matches nothing, program stays SAT (probed)
    Lo = Predicate.define("lo2", ["n"], show=False)
    Hi = Predicate.define("hi2", ["n"], show=False)
    W = Predicate.define("w", [])
    program = ASPProgram()
    L, H, X = Variable("L"), Variable("H"), Variable("X")
    program.fact(Lo(n=5), Hi(n=2), W())
    program.when(Lo(n=L), Hi(n=H), X.in_(RangePool(L, H))).derive(Q(x=X))
    model = next(iter(program.solve()))
    assert model.atoms(Q) == []
    assert len(model.atoms(W)) == 1


def test_literal_empty_range_still_rejected_statically() -> None:
    with pytest.raises(ValueError, match="empty"):
        RangePool(5, 2)


def test_string_bounds_rejected() -> None:
    with pytest.raises(TypeError, match="got str"):
        RangePool(1, "high")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer-valued"):
        RangePool(1, String("high"))  # type: ignore[arg-type]


def test_unbound_range_variable_rejected_at_construction() -> None:
    # gringo rejects q(X) :- X = 1..N with N unbound (probed); so do we,
    # at the author's line
    program = ASPProgram()
    N, X = Variable("N"), Variable("X")
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.when(X.in_(RangePool(1, N))).derive(Q(x=X))


def test_ranges_never_invert() -> None:
    # gringo rejects deriving N from X = 1..N with X bound (probed): the
    # binding edge is one-way, so this is unsafe at construction too
    program = ASPProgram()
    P = Predicate.define("p_inv", ["x"], show=False)
    N, X = Variable("N"), Variable("X")
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.when(P(x=X), X.in_(RangePool(1, N))).derive(Q(x=N))


def test_variable_range_inside_aggregate_condition() -> None:
    # K = #count{ X : X = 1..N, c(X) }  (probed)
    C = Predicate.define("c", ["x"], show=False)
    Out = Predicate.define("n_out", ["k"])
    program = ASPProgram()
    N, K, X = Variable("N"), Variable("K"), Variable("X")
    program.fact(Size(n=3), C(x=2), C(x=7))
    program.when(Size(n=N), K == Count(X, condition=[X.in_(RangePool(1, N)), C(x=X)])).derive(Out(k=K))
    model = next(iter(program.solve()))
    assert [a["k"].value for a in model.atoms(Out)] == [1]


def test_ungrounded_range_facts_rejected() -> None:
    program = ASPProgram()
    N = Variable("N")
    with pytest.raises(ValueError, match="grounded"):
        program.fact(Q(x=RangePool(1, N)))


def test_anonymous_variable_rejected_in_range_bounds() -> None:
    # '_' in a bound matches anything and binds nothing: gringo rejects the
    # rule as unsafe (each _ is a fresh unbound variable), and the empty
    # variable set would otherwise fool the binding analysis into marking
    # the compared side bound
    with pytest.raises(ValueError, match="cannot appear in a range end"):
        RangePool(1, ANY)
    with pytest.raises(ValueError, match="cannot appear in a range start"):
        RangePool(ANY, 5)
    with pytest.raises(ValueError, match="cannot appear in a range end"):
        RangePool(1, ANY + 1)  # nested in an expression, same rejection
