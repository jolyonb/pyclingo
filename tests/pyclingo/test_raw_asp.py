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
