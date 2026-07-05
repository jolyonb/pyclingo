"""
Tests for raw_asp: the verbatim-ASP escape hatch and its predicate seatbelt.
"""

import pytest

from pyclingo import ASPProgram, Predicate


def test_renders_verbatim() -> None:
    program = ASPProgram()
    program.raw_asp("foo(1..3).\n#minimize { X : foo(X) }.")
    rendered = program.render()
    assert "foo(1..3)." in rendered
    assert "#minimize { X : foo(X) }." in rendered


def test_declared_predicates_are_shown_and_round_trip() -> None:
    program = ASPProgram()
    Foo = Predicate.define("foo", ["x"])
    program.raw_asp("foo(1..3).", predicates=[Foo])

    assert "#show foo/1." in program.render()

    models = list(program.solve())
    assert len(models) == 1
    facts = models[0].atoms(Foo)
    assert sorted(f["x"].value for f in facts) == [1, 2, 3]
    assert all(isinstance(f, Foo) for f in facts)


def test_undeclared_shown_atoms_fail_loudly() -> None:
    program = ASPProgram()
    program.raw_asp("bar(1).\n#show bar/1.")
    with pytest.raises(ValueError, match="Unknown predicate type: bar"):
        list(program.solve())


def test_respects_segments() -> None:
    program = ASPProgram()
    Base = Predicate.define("base", ["x"])
    program.fact(Base(x=1))  # populate the default segment so headers render
    program.add_segment("extras")
    program.raw_asp("foo(1).", segment="extras")
    rendered = program.render()
    assert rendered.index("===== Extras =====") < rendered.index("foo(1).")


def test_constants_used_only_in_raw_text_are_emitted() -> None:
    # Filtering to walker-visible uses silently dropped these, making clingo
    # read the name as a symbol (numbers sort before symbols: wrong answers)
    program = ASPProgram()
    Val = Predicate.define("val", ["x"], show=False)
    Q = Predicate.define("q", ["x"])
    program.fact(*[Val(x=i) for i in range(1, 6)])
    program.define_constant("n", 3)
    program.raw_asp("q(X) :- val(X), X < n.", predicates=[Q])
    assert "#const n = 3." in program.render()
    model = next(iter(program.solve()))
    assert sorted(a["x"].value for a in model.atoms(Q)) == [1, 2]


def test_show_override_honored_for_raw_only_predicates() -> None:
    program = ASPProgram()
    Q = Predicate.define("q", ["x"], show=False)
    program.raw_asp("q(1).")  # forgot predicates=... but then explicitly:
    program.show(Q)
    assert "#show q/1." in program.render()
