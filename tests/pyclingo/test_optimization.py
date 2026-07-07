"""
Tests for #minimize/#maximize authoring: rendering (weight@priority,
tuples, conditions), element scoping (a directive has no rule body, so
everything binds inside the element), and end-to-end behavior probed
against clasp (same-priority statements merge additively; maximize
reports negated costs; priorities are ordinal keys with free gaps).
"""

import clingo
import pytest

from pyclingo import ANY, ASPProgram, Choice, Count, Predicate, String, Variable


def optimal_cost(program: ASPProgram) -> list[int]:
    """Ground and fully descend via clingo directly; cost plumbing arrives with the solving verbs."""
    ctl = clingo.Control(logger=lambda c, m: None)
    solve_config = ctl.configuration.solve
    assert isinstance(solve_config, clingo.Configuration)
    solve_config.models = 0
    ctl.add("base", [], program.render())
    ctl.ground([("base", [])])
    cost: list[int] = []
    with ctl.solve(yield_=True) as h:
        for model in h:
            cost = list(model.cost)
    return cost


Island = Predicate.define("island", ["loc", "size"], show=False)
Pick = Predicate.define("pick", ["x"])


def test_minimize_renders_weight_tuple_condition() -> None:
    program = ASPProgram()
    Size, C = Variable("Size"), Variable("C")
    program.fact(Island(loc=1, size=3))
    program.minimize(Size, C, condition=Island(loc=C, size=Size))
    assert "#minimize{ Size, C : island(C, Size) }." in program.render()


def test_priority_renders_at_form_and_zero_is_bare() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.fact(Pick(x=1))
    program.minimize(1, X, condition=Pick(x=X), priority=2)
    program.minimize(X, condition=Pick(x=X))  # priority 0: no @
    rendered = program.render()
    assert "#minimize{ 1@2, X : pick(X) }." in rendered
    assert "#minimize{ X : pick(X) }." in rendered


def test_maximize_renders() -> None:
    program = ASPProgram()
    X = Variable("X")
    program.fact(Pick(x=1))
    program.maximize(X, condition=Pick(x=X))
    assert "#maximize{ X : pick(X) }." in program.render()


def test_unbound_element_variable_rejected() -> None:
    # No rule body exists to bind W: it must bind inside the element
    program = ASPProgram()
    W, X = Variable("W"), Variable("X")
    with pytest.raises(ValueError, match="Unsafe variable"):
        program.minimize(W, X, condition=Pick(x=X))


def test_singleton_element_variable_rejected() -> None:
    program = ASPProgram()
    X, Y = Variable("X"), Variable("Y")
    Pair = Predicate.define("pair_opt", ["a", "b"])
    with pytest.raises(ValueError, match="Singleton variable"):
        program.minimize(X, condition=Pair(a=X, b=Y))


def test_weight_types_validated() -> None:
    program = ASPProgram()
    with pytest.raises(TypeError, match="got str"):
        program.minimize("three", condition=Pick(x=ANY))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer-valued"):
        program.minimize(String("three"), condition=Pick(x=ANY))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="priority must be an int"):
        program.minimize(1, condition=Pick(x=ANY), priority="high")  # type: ignore[arg-type]


def test_aggregate_condition_rejected() -> None:
    # ConditionedElement's shared guard covers optimization elements too
    program = ASPProgram()
    X, K = Variable("X"), Variable("K")
    with pytest.raises(ValueError, match="Aggregates cannot appear inside optimization conditions"):
        program.minimize(1, X, condition=[Pick(x=X), K == Count(X, condition=Pick(x=X))])


def test_grounds_cleanly() -> None:
    # The rendered directive is real gringo: grounding succeeds
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)))
    program.minimize(X, condition=Pick(x=X))
    grounded = program.ground()
    assert "#minimize" in grounded.text


def test_statements_share_one_tuple_set() -> None:
    # All optimization statements contribute to ONE tuple set: identical
    # tuples count once, distinct tuples sum
    X = Variable("X")

    duplicated = ASPProgram()
    duplicated.fact(Pick(x=1), Pick(x=2))
    duplicated.minimize(1, X, condition=Pick(x=X))
    duplicated.minimize(1, X, condition=Pick(x=X))  # identical tuples: dedup
    assert optimal_cost(duplicated) == [2]

    distinct = ASPProgram()
    distinct.fact(Pick(x=1), Pick(x=2))
    distinct.minimize(1, X, String("a"), condition=Pick(x=X))
    distinct.minimize(1, X, String("b"), condition=Pick(x=X))  # distinct tuples: sum
    assert optimal_cost(distinct) == [4]


def test_priority_gaps_are_free() -> None:
    # Priorities are ordinal keys: @3/@1 behaves exactly like dense levels
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(1, X, condition=Pick(x=X), priority=3)
    program.minimize(X, condition=Pick(x=X), priority=1)
    assert optimal_cost(program) == [1, 1]  # two entries, highest priority first, no phantom @2


def test_explicit_zero_renders_bare() -> None:
    # priority=0 and no priority are the same statement, byte-identical:
    # @0 is never rendered, so the two spellings cannot diverge
    explicit = ASPProgram()
    bare = ASPProgram()
    X = Variable("X")
    for program in (explicit, bare):
        program.fact(Pick(x=1))
    explicit.minimize(1, X, condition=Pick(x=X), priority=0)
    bare.minimize(1, X, condition=Pick(x=X))
    assert explicit.render() == bare.render()


def test_bare_statements_sit_at_priority_zero() -> None:
    # A statement without priority= IS priority 0: mixing bare and
    # prioritized statements creates distinct levels, bare least important
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).at_least(1))
    program.minimize(1, X, condition=Pick(x=X), priority=2)
    program.minimize(X, condition=Pick(x=X))  # bare: level 0
    assert optimal_cost(program) == [1, 1]  # [level 2, level 0], count then sum
