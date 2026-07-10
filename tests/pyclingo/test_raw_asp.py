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
    # The contract is enforced at ground time against gringo's own
    # signature table — before any model, UNSAT programs included
    with pytest.raises(ValueError, match="never declared to pyclingo: bar/1"):
        program.solve()


def test_respects_segments() -> None:
    program = ASPProgram()
    Base = Predicate.define("base", ["x"])
    program.fact(Base(x=1))  # populate the default segment so headers render
    program.add_segment("extras")
    program["extras"].raw_asp("foo(1).")
    rendered = program.render()
    assert rendered.index("===== extras =====") < rendered.index("foo(1).")


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


def test_undeclared_raw_atoms_fail_loudly_in_mixed_programs() -> None:
    # The raw_asp contract is exhaustive declaration: an atom whose signature
    # was never declared fails at the model, even though show directives
    # would have hidden it silently
    program = ASPProgram()
    P = Predicate.define("p_mixed", ["x"])
    program.fact(P(x=1))
    program.raw_asp("hidden_atom(42).")
    with pytest.raises(ValueError, match="never declared to pyclingo: hidden_atom/1"):
        program.solve()


def test_declared_scaffolding_stays_hidden_without_error() -> None:
    # Privacy is a visibility choice (show=False), not an omission: declared
    # scaffolding is checked, collision-guarded, and hidden from models
    program = ASPProgram()
    P = Predicate.define("p_scaf", ["x"])
    Reach = Predicate.define("reach", ["x"], show=False)
    program.fact(P(x=1))
    program.raw_asp("reach(1). reach(2).", predicates=[Reach])
    model = next(iter(program.solve()))
    assert [str(a) for a in model.atoms()] == ["p_scaf(1)"]


def test_exhaustive_declaration_catches_modelless_violations() -> None:
    # The ground-time check sees what a per-model scan structurally cannot:
    # undeclared predicates in UNSAT programs (no model ever arrives) and
    # predicates false in every model
    unsat = ASPProgram()
    unsat.raw_asp("helper(1).\n:- helper(1).")
    with pytest.raises(ValueError, match="never declared to pyclingo: helper/1"):
        unsat.solve()

    never_true = ASPProgram()
    Q = Predicate.define("q_raw_nt", ["x"])
    never_true.fact(Q(x=1))
    never_true.raw_asp("{ maybe(X) : q_raw_nt(X) }.\n:- maybe(X).")
    with pytest.raises(ValueError, match="never declared to pyclingo: maybe/1"):
        never_true.solve()


def test_all_undeclared_signatures_reported_at_once() -> None:
    program = ASPProgram()
    program.raw_asp("first(1).\nsecond(1, 2).")
    with pytest.raises(ValueError, match="first/1, second/2"):
        program.solve()


def test_const_atom_collision_diagnosed() -> None:
    # gringo substitutes #const only in TERM positions: the atom stays a
    # distinct symbol, silently. The signatures check names the collision.
    program = ASPProgram()
    program.define_constant("foo", 5)
    P = Predicate.define("p_cc", ["x"])
    program.fact(P(x=1))
    program.raw_asp("foo.")
    with pytest.raises(ValueError, match="both a #const and an atom"):
        program.solve()


def test_show_declares_as_fully_as_predicates() -> None:
    # The contract is "pyclingo must know the class", by any door:
    # show(Q) hands over the class object, so the grounding check accepts
    # and models round-trip — no predicates= needed
    Q = Predicate.define("q_door", ["x"])
    program = ASPProgram()
    program.raw_asp("q_door(1..3).")
    program.show(Q)
    model = next(iter(program.solve()))
    assert sorted(a["x"].value for a in model.atoms(Q)) == [1, 2, 3]


def test_raw_negated_atoms_declared_with_minus_predicate() -> None:
    # predicates= takes P for the positive sign and -P for the negative:
    # declaring -P emits "#show -p/1." so the raw block's -p atoms are visible
    P = Predicate.define("p_negraw", ["x"])
    program = ASPProgram()
    program.fact(P(x=1))
    program.raw_asp("-p_negraw(2).", predicates=[P, -P])
    assert "#show -p_negraw/1." in program.render()
    model = next(iter(program.solve()))
    negated = [a for a in model.atoms(P) if a.negated]
    assert [a["x"].value for a in negated] == [2]


def test_raw_positive_declaration_omits_the_negated_show() -> None:
    # Declaring only P covers round-trip/collision for both signs, but emits
    # only the positive #show; the -p atom stays out of output without -P
    P = Predicate.define("p_posonly", ["x"])
    program = ASPProgram()
    program.fact(P(x=1))
    program.raw_asp("-p_posonly(2).", predicates=[P])
    rendered = program.render()
    assert "#show p_posonly/1." in rendered
    assert "#show -p_posonly/1." not in rendered


def test_raw_show_term_forms_get_a_teaching_error() -> None:
    # #show term forms emit arbitrary non-atom output pyclingo cannot
    # model; the conversion error teaches instead of clingo's bare
    # RuntimeError("unexpected")
    P = Predicate.define("p_term", ["x"])
    program = ASPProgram()
    program.fact(P(x=2))
    program.raw_asp("#show 2*X : p_term(X).")
    result = program.solve()
    retained = iter(result)
    with pytest.raises(ValueError, match="non-predicate output"):
        next(retained)
    # The dead generator marks itself closed: the retained iterator stays
    # loud instead of silently reading as clean exhaustion
    with pytest.raises(RuntimeError, match="closed"):
        next(retained)


def test_part_directives_rejected_with_teaching() -> None:
    # A #program part directive silently unloads everything rendered after
    # it (the program grounds a single 'base' part): empty model, SAT — a
    # silent wrong answer caught at construction instead
    program = ASPProgram()
    with pytest.raises(ValueError, match="unloaded part"):
        program.raw_asp("#program later.")
    with pytest.raises(ValueError, match="unloaded part"):
        program.raw_asp('#include "other.lp".')


def test_part_directives_in_comments_and_scripts_are_inert() -> None:
    # Commented-out, string-embedded, and #script-embedded text is not a
    # directive — and gringo NESTS block comments, so an inner *% does not
    # end the outer comment
    program = ASPProgram()
    P = Predicate.define("p_inert", ["x"])
    program.raw_asp("% #program later.\np_inert(1).", predicates=[P])
    program.raw_asp("%*\n#program block.\n*%\np_inert(2).")
    program.raw_asp("%*\nouter %* inner *%\n#program still_commented.\n*%\np_inert(3).")
    program.raw_asp('p_inert("#program in a string").')
    program.raw_asp('#script (python)\ntext = "#program fake."\n#end.')
    program.raw_asp("p_inert(4). % a trailing comment mentioning #program, no newline")
    assert "p_inert(1)." in program.render()
    # An unterminated #script swallows the rest of the scan (gringo itself
    # rejects the block at parse, so the scan need not judge its interior)
    throwaway = ASPProgram()
    throwaway.raw_asp("#script (python)\n#program fake.")


def test_external_rejected_with_teaching() -> None:
    # An #external atom's truth needs Control.assign_external, which no
    # pyclingo verb speaks: left unassigned it is false and rules through
    # it silently drop — rejected at construction, pointing at the
    # choice + assumptions spelling
    program = ASPProgram()
    with pytest.raises(ValueError, match=r"#external.*assign_external.*choose\(Choice\(\.\.\.\)\).*assumptions="):
        program.raw_asp("#external toggle(1).")


def test_external_in_comments_and_strings_is_inert() -> None:
    program = ASPProgram()
    P = Predicate.define("p_ext", ["x"])
    program.raw_asp("% #external note.\np_ext(1).", predicates=[P])
    program.raw_asp('p_ext("#external in a string").')
    assert "p_ext(1)." in program.render()


def test_part_directives_are_found_when_code_resumes_mid_line() -> None:
    # The scan is character-level: a directive after a same-line comment
    # close, or after a string containing %, is still live code
    program = ASPProgram()
    with pytest.raises(ValueError, match="unloaded part"):
        program.raw_asp("%* note *% #program later.")
    with pytest.raises(ValueError, match="unloaded part"):
        program.raw_asp('p("100%"). #program later.')
    with pytest.raises(ValueError, match="unloaded part"):
        program.raw_asp('p("esc\\"quote"). #program later.')  # the \\" escape does not end the string early


def test_predicates_entries_validated_at_the_call() -> None:
    # An instance rendered, grounded, and then died at the first model read
    # with "'p' object is not callable" — three stages from the author
    program = ASPProgram()
    P = Predicate.define("p_rawdecl", ["x"])
    with pytest.raises(TypeError, match="declares CLASSES, got the atom"):
        program.raw_asp("p_rawdecl(1).", predicates=[P(x=1)])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="must be Predicate classes"):
        program.raw_asp("p_rawdecl(1).", predicates=["p_rawdecl"])  # type: ignore[list-item]
    program.raw_asp("p_rawdecl(1).", predicates=[P, -P])  # classes and negated signs still pass
