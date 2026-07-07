from pyclingo import AtomCollection, CostedModel, Model, Predicate


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
