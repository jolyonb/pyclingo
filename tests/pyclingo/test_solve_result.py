import clingo
import pytest

from pyclingo import (
    AtomCollection,
    CostedModel,
    DefinedConstant,
    Model,
    OptimizeSteps,
    Predicate,
    RefinementSteps,
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


def test_convert_symbol_unsupported_argument_type_raises() -> None:
    # An argument that is neither Number, String, nor Function (here #sup) falls
    # through to the unsupported-symbol guard.
    P = Predicate.define("p_sup", ["x"])
    with pytest.raises(ValueError, match="Unsupported symbol type in argument"):
        convert_symbol_to_predicate(clingo.Function("p_sup", [clingo.Supremum]), {("p_sup", 1): P})
