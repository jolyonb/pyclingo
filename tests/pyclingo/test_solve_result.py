import clingo
import pytest

from pyclingo import (
    INF,
    SUP,
    ASPProgram,
    AtomCollection,
    CostedModel,
    DefinedConstant,
    Model,
    Number,
    OptimizeSteps,
    Predicate,
    RefinementSteps,
    Variable,
)
from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel
from pyclingo.solve_result import (
    RefinementMode,
    convert_predicate_to_symbol,
    convert_symbol_to_predicate,
)


def test_model_is_an_atom_collection() -> None:
    # AtomCollection is the claim-free reading surface; Model adds the
    # answer-set identity and messages
    P = Predicate.define("p_ac", ["x"])
    model = Model([P(x=1), P(x=2)])
    assert isinstance(model, AtomCollection)
    assert model.messages == []
    collection = AtomCollection([P(x=1)])
    assert len(collection) == 1
    assert collection.atoms(P)[0]["x"].value == 1
    assert not hasattr(collection, "messages")
    assert repr(collection).startswith("AtomCollection(")
    assert repr(model).startswith("Model(")


def test_costed_model_carries_its_cost() -> None:
    # An optimization emission is a genuine answer set plus its cost:
    # one entry per declared priority level, highest first, lower always
    # better (a maximization's cost arrives negated)
    P = Predicate.define("p_cm", ["x"])
    model = CostedModel([P(x=1)], cost=(2, 7))
    assert isinstance(model, Model)
    assert isinstance(model, AtomCollection)
    assert model.cost == (2, 7)
    assert model.messages == []
    assert model.atoms(P)[0]["x"].value == 1
    assert repr(model).startswith("CostedModel(cost=[2, 7]")


def test_optimize_steps_over_non_optimizing_program_raises() -> None:
    # Belt-and-suspenders backstop: OPTIMIZE mode expects every model to carry
    # a cost. Only reachable by hand-constructing the handle around a control
    # whose program has no #minimize/#maximize — the emitted model has no cost
    # to descend.
    Pick = Predicate.define("pick", ["x"])
    ctl = clingo.Control(logger=lambda code, msg: None)
    solve_config = ctl.configuration.solve
    assert isinstance(solve_config, clingo.Configuration)
    solve_config.models = 0
    ctl.add("base", [], "pick(1..2).")
    ctl.ground([("base", [])])
    handler = ClingoMessageHandler("", stop_on_level=LogLevel.CRITICAL)
    steps = OptimizeSteps(ctl, {("pick", 1): Pick}, 0, handler, [])
    with pytest.raises(ValueError, match="needs an optimizing program"):
        list(steps)


def test_refinement_over_optimizing_program_raises() -> None:
    # A refinement (cautious/brave) over an optimizing program would aggregate
    # the cost-descent path, not the optima — the answer would be wrong. The
    # API guards this statically; only a hand-built RefinementSteps around an
    # optimizing control reaches this runtime backstop.
    Pick = Predicate.define("pick", ["x"])
    ctl = clingo.Control(logger=lambda code, msg: None)
    solve_config = ctl.configuration.solve
    assert isinstance(solve_config, clingo.Configuration)
    solve_config.models = 0
    ctl.add("base", [], "pick(1..2). #minimize{ 1,X : pick(X) }.")
    ctl.ground([("base", [])])
    handler = ClingoMessageHandler("", stop_on_level=LogLevel.CRITICAL)
    steps = RefinementSteps(ctl, {("pick", 1): Pick}, 0, handler, [], mode=RefinementMode.CAUTIOUS)
    with pytest.raises(ValueError, match="cost-descent path"):
        list(steps)


def test_convert_predicate_unresolved_defined_constant_raises() -> None:
    # A #const reference with no value in the snapshot cannot become a symbol:
    # gringo substitutes constants at grounding, so the value must be known here.
    F = Predicate.define("f_const", ["x"])
    with pytest.raises(ValueError, match="no value for it is available"):
        convert_predicate_to_symbol(F(x=DefinedConstant("bogus")), {})


def test_convert_predicate_string_field_becomes_clingo_string() -> None:
    # A string-valued field routes through clingo.String.
    P = Predicate.define("p_str", ["name"])
    symbol = convert_predicate_to_symbol(P(name="foo"))
    assert symbol.name == "p_str"
    assert symbol.arguments[0] == clingo.String("foo")


def test_convert_predicate_nested_predicate_recurses() -> None:
    # A predicate-valued field recurses back into convert_predicate_to_symbol.
    Inner = Predicate.define("inner", ["x"])
    Outer = Predicate.define("outer", ["cell"])
    symbol = convert_predicate_to_symbol(Outer(cell=Inner(x=1)))
    assert symbol.name == "outer"
    nested = symbol.arguments[0]
    assert nested.name == "inner"
    assert nested.arguments[0] == clingo.Number(1)


def test_convert_symbol_unknown_predicate_type_raises() -> None:
    # A model symbol whose (name, arity) is not a declared predicate type is
    # rejected — e.g. an atom from a raw_asp() block with no declared class.
    with pytest.raises(ValueError, match="Unknown predicate type"):
        convert_symbol_to_predicate(clingo.Function("mystery", [clingo.Number(1)]), {})


def test_convert_symbol_extreme_arguments_become_the_singletons() -> None:
    # #sup/#inf arguments round-trip as the interned SUP/INF values
    P = Predicate.define("p_sup", ["x"])
    atom = convert_symbol_to_predicate(clingo.Function("p_sup", [clingo.Supremum]), {("p_sup", 1): P})
    assert atom["x"] is SUP
    atom = convert_symbol_to_predicate(clingo.Function("p_sup", [clingo.Infimum]), {("p_sup", 1): P})
    assert atom["x"] is INF
    # And back again, in the mirror converter
    assert convert_predicate_to_symbol(P(x=SUP)) == clingo.Function("p_sup", [clingo.Supremum])
    assert convert_predicate_to_symbol(P(x=INF)) == clingo.Function("p_sup", [clingo.Infimum])


def test_atoms_rejects_instances_and_non_classes() -> None:
    # atoms(instance) silently returned [] — the exact silent-empty failure
    # the closed-iterator guards exist to prevent elsewhere
    program = ASPProgram()
    P = Predicate.define("p_atomcls", ["x"])
    program.fact(P(x=1))
    model = next(iter(program.solve()))
    with pytest.raises(TypeError, match="pass the class p_atomcls"):
        model.atoms(P(x=1))  # type: ignore[call-overload]
    with pytest.raises(TypeError, match="takes a Predicate class, got int"):
        model.atoms(int)  # type: ignore[type-var]


def test_first_returns_one_model_and_frees_the_grounding() -> None:
    program = ASPProgram()
    P = Predicate.define("p_first", ["x"])
    program.fact(P(x=1))
    grounded = program.ground()
    model = grounded.solve().first()
    assert isinstance(model, Model)
    assert model.atoms(P)[0]["x"] is Number(1)  # interned: identity is value
    grounded.solve().close()  # first() closed its search: no still-open guard


def test_first_on_unsatisfiable_raises_teaching() -> None:
    program = ASPProgram()
    P = Predicate.define("p_first_unsat", ["x"])
    program.fact(P(x=1))
    program.forbid(P(x=1))
    with pytest.raises(ValueError, match=r"unsatisfiable.*next\(iter\(result\), None\)"):
        program.solve().first()


def test_model_iterates_and_answers_membership() -> None:
    program = ASPProgram()
    P = Predicate.define("p_member", ["x"])
    program.fact(P(x=1), P(x=2))
    model = program.solve().first()
    assert sorted(str(atom) for atom in model) == ["p_member(1)", "p_member(2)"]
    assert P(x=1) in model
    assert P(x=3) not in model


def test_model_membership_rejects_what_could_never_be_present() -> None:
    program = ASPProgram()
    P = Predicate.define("p_member_guard", ["x"])
    program.fact(P(x=1))
    model = program.solve().first()
    with pytest.raises(TypeError, match=r"got the class p_member_guard.*atoms\(p_member_guard\)"):
        P in model  # type: ignore[operator]  # noqa: B015 (the membership test is the act under test)
    with pytest.raises(TypeError, match="got str"):
        "p_member_guard(1)" in model  # type: ignore[operator]  # noqa: B015
    with pytest.raises(ValueError, match="contains variables"):
        P(x=Variable("X")) in model  # noqa: B015
