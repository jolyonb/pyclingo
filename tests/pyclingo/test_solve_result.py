from pyclingo import AtomCollection, Model, Predicate


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
