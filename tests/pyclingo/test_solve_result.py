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
    PyClingoError,
    RefinementSteps,
    UnsatisfiableError,
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
    assert model.messages == ()
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
    assert model.messages == ()
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


def test_first_refuses_a_partially_consumed_stream() -> None:
    # first() is the one-answer sugar, not a cursor: after models have been
    # pulled by hand, "the first" would be a lie
    program = ASPProgram()
    P = Predicate.define("p_first_cursor", ["x"])
    program.fact(P(x=1), P(x=2))  # one model, but the guard fires on yields, not truth
    result = program.solve()
    next(iter(result))
    with pytest.raises(RuntimeError, match=r"already yielded 1 model.*solve\(\) again"):
        result.first()


def test_first_on_unsatisfiable_raises_teaching() -> None:
    program = ASPProgram()
    P = Predicate.define("p_first_unsat", ["x"])
    program.fact(P(x=1))
    program.forbid(P(x=1))
    with pytest.raises(UnsatisfiableError, match=r"unsatisfiable.*next\(iter\(result\), None\)"):
        program.solve().first()
    # An outcome, not a mistake: NOT a ValueError (a validation except
    # clause must never absorb UNSAT), rooted at pyclingo's own base
    assert not issubclass(UnsatisfiableError, ValueError)
    assert issubclass(UnsatisfiableError, PyClingoError)


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


def test_membership_teaches_on_const_bearing_atoms() -> None:
    # gringo substitutes #const at grounding, so p(c) can never be a model
    # atom — a quiet False here answered the wrong question (probed: the
    # model holds p(3), and the same p(v=c) works as an assumption)
    program = ASPProgram()
    P = Predicate.define("p_member_const", ["v"])
    c = program.define_constant("c_member", 3)
    program.fact(P(v=c))
    model = program.solve().first()
    assert P(v=3) in model  # the resolved value is the member
    with pytest.raises(ValueError, match=r"references #const c_member.*resolved values.*plain value"):
        P(v=c) in model  # noqa: B015 (the membership test is the act under test)


def test_hidden_class_reads_teach_instead_of_silent_empty() -> None:
    # show=False keeps helper atoms out of results BY DESIGN (never touching
    # them is what keeps model reads fast at scale); asking for one must
    # explain that, never return an [] that reads as "none were derived"
    P = Predicate.define("p_vis", ["x"])
    H = Predicate.define("h_vis", ["x"], show=False)
    program = ASPProgram()
    program.fact(P(x=1), H(x=2))
    model = program.solve().first()
    with pytest.raises(ValueError, match=r"h_vis/1 is hidden.*show\(\) the class"):
        model.atoms(H)
    with pytest.raises(ValueError, match="h_vis/1 is hidden"):
        H(x=2) in model  # noqa: B015 (membership is a read too)
    assert model.atoms(P) == [P(x=1)]  # shown classes read as before


def test_show_override_makes_a_hidden_class_readable() -> None:
    # show() flips the resolution: the atoms are in the result and read fine
    H = Predicate.define("h_vis_shown", ["x"], show=False)
    program = ASPProgram()
    program.fact(H(x=1))
    program.show(H)
    model = program.solve().first()
    assert model.atoms(H) == [H(x=1)]


def test_hide_override_teaches_like_show_false() -> None:
    # hide() of a default-shown class enters the same teaching wall
    P = Predicate.define("p_vis_hidden", ["x"])
    program = ASPProgram()
    program.fact(P(x=1))
    program.hide(P)
    model = program.solve().first()
    with pytest.raises(ValueError, match="p_vis_hidden/1 is hidden"):
        model.atoms(P)


def test_underived_shown_class_still_reads_empty() -> None:
    # An empty [] remains the honest answer when the class is SHOWN but the
    # solver derived nothing — only hiddenness is loud
    P = Predicate.define("p_vis_used", ["x"])
    Q = Predicate.define("q_vis_maybe", ["x"])
    program = ASPProgram()
    program.fact(P(x=1))
    program.when(P(x=2)).derive(Q(x=2))  # body never true: no q atoms
    model = program.solve().first()
    assert model.atoms(Q) == []


def test_close_passes_through_foreign_value_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # close() translates only the generator-machinery "already executing"
    # ValueError; a genuine ValueError out of the generator's finalization
    # must surface as itself, never relabeled as a concurrency problem
    program = ASPProgram()
    P = Predicate.define("p_close_passthrough", ["x"])
    program.fact(P(x=1))
    result = program.solve()

    def exploding_close(self: object) -> None:
        raise ValueError("finalization went sideways")

    monkeypatch.setattr(type(result._iterator), "close", exploding_close)
    with pytest.raises(ValueError, match="finalization went sideways"):
        result.close()


def test_executing_discriminator_ignores_lookalike_message_text() -> None:
    # The concurrency translation matches Python's machinery message EXACTLY:
    # a genuine ValueError whose text merely contains the phrase (a raw
    # #show term form embedding model data) must surface as itself, not as
    # a phantom threading diagnosis
    P = Predicate.define("p_lookalike", ["x"])
    program = ASPProgram()
    program.fact(P(x=1))
    program.raw_asp('#show "this generator is already executing" : p_lookalike(1).', predicates=[P])
    with pytest.raises(ValueError, match="non-predicate output"):
        next(iter(program.solve()))
