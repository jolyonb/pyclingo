"""
Tests for GroundedProgram.statement_profile()/analyze_statements(): per-
statement ground instantiation counts via an instrumented re-ground. Where
grounding_profile() counts the atoms a signature ends up with (and so
cannot see constraints or wide-bodied rules), the statement profile
charges every statement its own row.
"""

import itertools

import clingo
import pytest

from aspalchemy import (
    ANY,
    ASPProgram,
    Choice,
    ConditionalLiteral,
    Count,
    NegatedSignature,
    Predicate,
    RangePool,
    StatementGrounding,
    Variable,
)
from aspalchemy.analysis import (
    _has_rule_arrow,
    _instrument_source,
    _rename_anonymous,
    _rewrite_weak_priority,
    _split_weak_tail,
    _statement_complete,
)

Cell = Predicate.define("cell_sp", ["x", "y"])
Pair = Predicate.define("pair_sp", ["a", "b"])


def build() -> ASPProgram:
    program = ASPProgram()
    X, Y, A, B = Variable("X"), Variable("Y"), Variable("A"), Variable("B")
    program.when(X.in_(RangePool(1, 3)), Y.in_(RangePool(1, 3))).derive(Cell(X, Y))
    program.when(Cell(A, Y), Cell(B, Y)).derive(Pair(A, B))
    program.forbid(Pair(A, B), Pair(B, A), A != B)
    return program


def by_statement(profile: tuple[StatementGrounding, ...]) -> dict[str, StatementGrounding]:
    return {row.statement: row for row in profile}


def test_counts_facts_rules_and_constraints() -> None:
    profile = build().ground().statement_profile()
    rows = by_statement(profile)
    # The pool fact instantiates 9 cells; the join makes 27 pairs (3 rows
    # of 3x3 orderings); the constraint fires on the 6 ordered unequal pairs
    assert rows["cell_sp(X, Y) :- X = 1..3, Y = 1..3."].instances == 9
    assert rows["pair_sp(A, B) :- cell_sp(A, Y), cell_sp(B, Y)."].instances == 27
    assert rows[":- pair_sp(A, B), pair_sp(B, A), A != B."].instances == 6


def test_sorted_largest_first_with_locations() -> None:
    profile = build().ground().statement_profile()
    counts = [row.instances for row in profile]
    assert counts == sorted(counts, reverse=True)
    for row in profile:
        assert row.location is not None
        assert row.location.filename.endswith("test_statement_profile.py")


def test_constraints_charge_their_own_rows_unlike_the_signature_profile() -> None:
    # The motivating case: a constraint has no head, so grounding_profile()
    # cannot attribute its cost anywhere — the statement profile can
    grounded = build().ground()
    signature_names = {entry.name for entry in grounded.grounding_profile()}
    assert not any(name.startswith(":-") for name in signature_names)
    constraint_rows = [row for row in grounded.statement_profile() if row.statement.startswith(":-")]
    assert len(constraint_rows) == 1
    assert constraint_rows[0].instances == 6


def test_choice_rules_count_their_instantiations() -> None:
    Pick = Predicate.define("pick_sp", ["x"])
    On = Predicate.define("on_sp", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.when(X.in_(RangePool(1, 4))).derive(On(x=X))
    program.when(On(x=X)).choose(Choice(Pick(x=X)))
    rows = by_statement(program.ground().statement_profile())
    assert rows["{ pick_sp(X) } :- on_sp(X)."].instances == 4


def test_bare_facts_and_strings_with_rule_arrows_inside() -> None:
    # A fact whose string argument contains ':- ' and a trailing '.' must be
    # instrumented as a fact (marker attached with ':-'), not as a rule
    Note = Predicate.define("note_sp", ["text"])
    program = ASPProgram()
    program.fact(Note(text="a :- b."))
    rows = by_statement(program.ground().statement_profile())
    assert rows['note_sp("a :- b.").'].instances == 1


def test_empty_program_profiles_empty() -> None:
    assert ASPProgram().ground().statement_profile() == ()


def test_directives_comments_and_weak_constraints() -> None:
    Pick = Predicate.define("pick_wc", ["x"])
    program = ASPProgram()
    program.section("a comment line")
    program.choose(Choice(Pick(x=RangePool(1, 3))))
    X = Variable("X")
    program.penalize(Pick(x=X), weight=1, terms=[X])
    profile = program.ground().statement_profile()
    rows = by_statement(profile)
    # The choice fact counts gringo's per-element ground rules; the weak
    # constraint's body work charges its own row; #show directives and
    # comments are not statement rows
    assert len(profile) == 2
    choice_row = next(statement for statement in rows if statement.startswith("{"))
    assert rows[choice_row].instances == 3
    weak_row = next(statement for statement in rows if statement.startswith(":~"))
    assert rows[weak_row].instances == 3


def test_multiline_raw_statements_pass_through_uncounted() -> None:
    P = Predicate.define("p_ml", ["x"])
    program = ASPProgram()
    program.raw_asp("p_ml(1).\np_ml(2) :-\n    p_ml(1).", predicates=[P])
    rows = by_statement(program.ground().statement_profile())
    # The single-line fact is counted; the split rule is left untouched
    assert rows["p_ml(1)."].instances == 1
    assert not any("p_ml(2)" in statement for statement in rows)


def test_script_blocks_are_never_instrumented() -> None:
    # This clingo build cannot ground #script blocks, so the span skipping
    # is pinned on the pure instrumentation function instead: the whole
    # text is raw (statement_table empty), and the #script span must pass
    # through the residual textual scan untouched
    text = "#script (python)\ndef f():\n    pass\n#end.\np_scr(1).\n"
    raw_locations = dict.fromkeys(range(1, 6))
    instrumented, tagged = _instrument_source(text, {}, raw_locations)
    assert list(tagged) == [5]
    # Facts are counted by companion rules; the fact itself stays real
    assert "__aspalchemy_fact(p_scr(1)) :- __aspalchemy_stmt(5)." in instrumented
    assert "def f():" in instrumented  # script body untouched
    assert "pass, __aspalchemy_stmt" not in instrumented


def test_context_bearing_groundings_profile_in_process() -> None:
    class Doubler:
        @staticmethod
        def double(x: clingo.Symbol) -> clingo.Symbol:
            return clingo.Number(x.number * 2)

    P = Predicate.define("p_ctxsp", ["x"])
    program = ASPProgram()
    program.raw_asp("p_ctxsp(@double(3)).", predicates=[P])
    rows = by_statement(program.ground(context=Doubler()).statement_profile())
    assert rows["p_ctxsp(@double(3))."].instances == 1


def test_stateful_context_divergence_is_loud() -> None:
    class OneShot:
        def __init__(self) -> None:
            self.calls = 0

        def val(self) -> clingo.Symbol:
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("spent")
            return clingo.Number(7)

    P = Predicate.define("p_oneshot_sp", ["x"])
    program = ASPProgram()
    program.raw_asp("p_oneshot_sp(@val()).", predicates=[P])
    grounded = program.ground(context=OneShot())
    with pytest.raises(RuntimeError, match=r"statement profile.*stateful @-function context(.|\n)*spent"):
        grounded.statement_profile()


def test_locations_off_reads_unknown() -> None:
    P = Predicate.define("p_nl", ["x"])
    program = ASPProgram(source_locations=False)
    program.fact(P(x=1))
    grounded = program.ground()
    assert grounded.statement_profile()[0].location is None
    assert "unknown (source locations off)" in grounded.analyze_statements()


def test_analyze_statements_prose() -> None:
    Long = Predicate.define("p_longname_for_truncation_purposes_sp", ["a", "b", "c", "d", "e", "f"])
    program = build()
    program.fact(Long(1_000_001, 2_000_002, 3_000_003, 4_000_004, 5_000_005, 6_000_006))
    prose = program.ground().analyze_statements()
    lines = prose.splitlines()
    assert lines[0] == "Statement profile: 43 ground instantiations across 4 statements"
    assert "pair_sp(A, B) :- cell_sp(A, Y), cell_sp(B, Y)." in lines[1]  # largest first
    assert "test_statement_profile.py:" in lines[1]
    assert any("..." in line for line in lines)  # the long fact is truncated


def test_helper_edges() -> None:
    assert _has_rule_arrow("p :- q")
    assert not _has_rule_arrow('p(":- not really")')
    assert _has_rule_arrow('p("\\":-\\"") :- q')  # escaped quotes end; the real arrow is found
    assert not _has_rule_arrow('p("unterminated')
    assert _statement_complete("p.")
    assert _statement_complete(":~ q(X). [1@1, X]")
    assert not _statement_complete("p :-")


def test_trailing_conditional_literal_counts_the_rule_not_the_condition() -> None:
    # Audit regression: ', marker' after a trailing conditional literal is
    # absorbed into the CONDITION by gringo's grammar (miscounting 6 for 3
    # and un-gating the rule); the '; ' joiner keeps the marker a body literal
    P = Predicate.define("p_cl", ["x"])
    Q = Predicate.define("q_cl", ["x"])
    R = Predicate.define("r_cl", ["x"])
    program = ASPProgram()
    X, Y = Variable("X"), Variable("Y")
    program.fact(*(P(x=i) for i in range(1, 4)))
    program.fact(*(Q(x=i) for i in range(1, 3)))
    program.when(P(x=X), ConditionalLiteral(X <= Y, Q(x=Y))).derive(R(x=X))
    rows = by_statement(program.ground().statement_profile())
    # Facts stay real in the instrumented copy, so the ground-evaluable
    # conditional resolves exactly as the true grounding: one emitted
    # instance (X=1; the X=2,3 instances fail the condition and are
    # dropped by gringo in both worlds). A ','-joined marker would have
    # been absorbed into the condition and miscounted.
    assert rows["r_cl(X) :- p_cl(X), X <= Y : q_cl(Y)."].instances == 1


def test_renderer_multiline_comments_do_not_derail_the_profile() -> None:
    # Audit regression: Comment.render() emits '%* ... *%' for multi-line
    # text; those lines must not open a phantom continuation or be tagged
    P = Predicate.define("p_mlc", ["x"])
    program = ASPProgram()
    program.comment("first line of a note\nsecond line, ending with a period.")
    program.fact(P(x=RangePool(1, 4)))
    rows = by_statement(program.ground().statement_profile())
    assert rows["p_mlc(1..4)."].instances == 4
    assert not any("note" in statement for statement in rows)


def test_raw_block_comments_and_trailing_comments() -> None:
    # Audit regression: block comments in raw text, and a raw statement
    # carrying a trailing '%' comment, must leave following statements counted
    P = Predicate.define("p_bc", ["x"])
    Q = Predicate.define("q_bc", ["text"])
    program = ASPProgram()
    program.raw_asp(
        "%* start of note\nstill inside the note *%\np_bc(1). % seed value\np_bc(2).\n"
        '\n% a whole-line comment\nq_bc("50% off").',
        predicates=[P, Q],
    )
    rows = by_statement(program.ground().statement_profile())
    assert rows["p_bc(1)."].instances == 1
    assert rows["p_bc(2)."].instances == 1
    # A '%' inside a string argument is not a comment; blank and
    # comment-only lines inside raw text are not statements
    assert rows['q_bc("50% off").'].instances == 1
    assert not any("whole-line" in statement for statement in rows)


def test_marker_lookalikes_never_crash_or_miscount() -> None:
    # Audit regression: a predicate SUFFIXED with the marker name, and
    # marker-shaped text inside string arguments, must neither KeyError nor
    # inflate counts
    Legit = Predicate.define("legit__aspalchemy_stmt", ["x"])
    R = Predicate.define("r_lk", ["x"])
    Note = Predicate.define("note_lk", ["text"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(Legit(x=7))
    program.when(Legit(x=X)).derive(R(x=X))
    program.fact(Note(text="see __aspalchemy_stmt(999) for details"))
    program.fact(Note(text="call __aspalchemy_stmt(2) maybe"))
    profile = program.ground().statement_profile()
    assert all(row.instances == 1 for row in profile)


def test_anonymous_variables_count_the_join_not_the_projection() -> None:
    # Audit regression: gringo rewrites '_' into a projection whose
    # auxiliary join rules carry no marker; renaming anonymous variables
    # apart restores the statement's true instantiation count
    Filled = Predicate.define("filled_av", ["r", "c"])
    Col = Predicate.define("col_av", ["c"])
    program = ASPProgram()
    R, C = Variable("R"), Variable("C")
    program.when(R.in_(RangePool(1, 10)), C.in_(RangePool(1, 10))).derive(Filled(r=R, c=C))
    program.when(Filled(r=ANY, c=C)).derive(Col(c=C))
    rows = by_statement(program.ground().statement_profile())
    assert rows["col_av(C) :- filled_av(_, C)."].instances == 100


def test_aggregates_over_facts_match_the_real_grounding() -> None:
    # Audit regression: facts gated behind the marker choice made
    # assignment aggregates ground over every achievable value (51 rows
    # for a 1-row real grounding, superlinear blowup). Facts now stay
    # real, so the aggregate evaluates exactly as the true grounding.
    Giv = Predicate.define("giv_ag", ["x"])
    Total = Predicate.define("total_ag", ["n"])
    program = ASPProgram()
    X, N = Variable("X"), Variable("N")
    program.fact(Giv(x=RangePool(1, 50)))
    program.when(N == Count(X, condition=Giv(x=X))).derive(Total(n=N))
    rows = by_statement(program.ground().statement_profile())
    assert rows["giv_ag(1..50)."].instances == 50
    aggregate_row = next(statement for statement in rows if "total_ag" in statement)
    assert rows[aggregate_row].instances == 1


def test_raw_range_split_across_lines_passes_through() -> None:
    # Audit regression: a line ending in '..' is an OPEN statement, not a
    # complete one; tagging it produced a syntax error blamed on contexts
    P = Predicate.define("p_rg", ["x"])
    Q = Predicate.define("q_rg", ["x"])
    program = ASPProgram()
    program.raw_asp("p_rg(1..\n3).\nq_rg(7).", predicates=[P, Q])
    rows = by_statement(program.ground().statement_profile())
    assert rows["q_rg(7)."].instances == 1
    assert not any("p_rg" in statement for statement in rows)  # multi-line: uncounted, documented


def test_classically_negated_facts_ride_the_companion() -> None:
    # A '-p' head sheds its sign for the companion argument (the count is
    # sign-independent), so the fact stays REAL and aggregates over it
    # evaluate exactly as the true grounding (gating would make the
    # aggregate ground over every achievable value)
    P = Predicate.define("np_cn", ["x"])
    C = Predicate.define("cnt_cn", ["n"])
    program = ASPProgram()
    program.raw_asp(
        "-np_cn(1;2;3).\ncnt_cn(N) :- N = #count{ X : -np_cn(X) }.",
        predicates=[NegatedSignature(P), C],
    )
    rows = by_statement(program.ground().statement_profile())
    assert rows["-np_cn(1;2;3)."].instances == 3
    assert rows["cnt_cn(N) :- N = #count{ X : -np_cn(X) }."].instances == 1


def test_anonymous_rename_in_raw_and_strings() -> None:
    # A '_' inside a string argument is untouched; a raw rule's '_' is
    # renamed apart and counts its full join
    P = Predicate.define("p_rs", ["a", "b"])
    D = Predicate.define("d_rs", ["a"])
    Note = Predicate.define("note_rs", ["t"])
    program = ASPProgram()
    C = Predicate.define("c_rs", ["x"])
    E = Predicate.define("e_rs", ["a"])
    program.raw_asp(
        'p_rs(1..3, 1..2).\nd_rs(A) :- p_rs(A, _).\nnote_rs("keep _ here").\n'
        '{ c_rs(1..2) }.\ne_rs(A) :- p_rs(A, 1), note_rs("keep _ here").',
        predicates=[P, D, Note, C, E],
    )
    rows = by_statement(program.ground().statement_profile())
    assert rows["d_rs(A) :- p_rs(A, _)."].instances == 6
    assert rows['note_rs("keep _ here").'].instances == 1
    assert rows["{ c_rs(1..2) }."].instances == 2  # raw bare choice: per-element ground rules
    # The rename pass walks the rule's string untouched
    assert rows['e_rs(A) :- p_rs(A, 1), note_rs("keep _ here").'].instances == 3


def test_anonymous_under_negation_is_left_alone() -> None:
    # Round-3 regression (crashed shipping minesweeper): 'not p(_)' is
    # legal, 'not p(V)' with V nowhere else is unsafe — negated anons must
    # not be renamed. Positive anons in the same statement still are.
    Cell = Predicate.define("cell_nn", ["x"])
    Num = Predicate.define("num_nn", ["x", "v"])
    Mine = Predicate.define("mine_nn", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(Cell(x=RangePool(1, 5)))
    program.fact(Num(x=2, v=1))
    program.when(Cell(x=X), ~Num(x=X, v=ANY)).choose(Choice(Mine(x=X)))
    rows = by_statement(program.ground().statement_profile())
    choice_row = next(statement for statement in rows if statement.startswith("{"))
    assert rows[choice_row].instances == 4  # cells 1,3,4,5 — cell 2 has a number


def test_weak_constraints_over_facts_count_their_instances() -> None:
    # Round-3 regression: a weak body over facts simplifies to nothing and
    # emits no auxiliary rule; the reserved-priority channel counts the
    # minimize entries instead — with the body untouched
    P = Predicate.define("p_wf", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(P(x=RangePool(1, 3)))
    program.penalize(P(x=X), weight=1, terms=[X])
    rows = by_statement(program.ground().statement_profile())
    weak_row = next(statement for statement in rows if statement.startswith(":~"))
    assert rows[weak_row].instances == 3


def test_weak_tail_with_dot_bracket_string_term() -> None:
    # Round-3 regression: the tail delimiter is found outside strings, so
    # a '. [' inside a terms string cannot swallow the redirect
    P = Predicate.define("p_ws", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(P(x=RangePool(1, 2))))
    program.penalize(P(x=X), weight=1, terms=[X, "x. [y"])
    rows = by_statement(program.ground().statement_profile())
    weak_row = next(statement for statement in rows if statement.startswith(":~"))
    assert rows[weak_row].instances == 2


def test_weak_variable_priority_stays_uncounted() -> None:
    # A non-integer priority cannot be redirected (unreachable from the
    # renderer, whose priorities are integers); the statement passes
    # through untagged rather than perturbed
    instrumented, tagged = _instrument_source(":~ p_vp(P). [1@P]\n", {1: (":~ p_vp(P). [1@P]", None, "weak")}, {})
    assert tagged == {}
    assert instrumented.startswith(":~ p_vp(P). [1@P]")


def test_two_statements_sharing_a_raw_line_pass_through() -> None:
    # Round-3 regression: the companion cannot wrap 'ta(1). tb(2)';
    # line-based attribution passes the line through uncounted
    TA = Predicate.define("ta_2f", ["x"])
    TB = Predicate.define("tb_2f", ["x"])
    Q = Predicate.define("q_2f", ["x"])
    program = ASPProgram()
    program.raw_asp("ta_2f(1). tb_2f(2).\nq_2f(7).", predicates=[TA, TB, Q])
    rows = by_statement(program.ground().statement_profile())
    assert rows["q_2f(7)."].instances == 1
    assert not any("ta_2f" in statement for statement in rows)


def test_raw_disjunctive_and_conditional_heads_are_gated() -> None:
    # Round-3 regression: a head-level ';' would be reinterpreted as a
    # pool inside the companion (2 for 1); a conditional head would be a
    # syntax error. Both gate instead.
    P = Predicate.define("p_dj", ["x"])
    Q = Predicate.define("q_dj", ["x"])
    R = Predicate.define("r_dj", ["x"])
    program = ASPProgram()
    program.fact(Q(x=RangePool(1, 2)))
    program.raw_asp("p_dj(1); p_dj(2).\nr_dj(X) : q_dj(X).", predicates=[P, R])
    rows = by_statement(program.ground().statement_profile())
    assert rows["p_dj(1); p_dj(2)."].instances == 1  # one disjunctive rule, not a pool of two
    assert rows["r_dj(X) : q_dj(X)."].instances == 1  # one conditional-head rule


def test_raw_weak_tail_on_its_own_line_does_not_swallow_the_next_statement() -> None:
    P = Predicate.define("p_wt", ["x"])
    Q = Predicate.define("q_wt", ["x"])
    program = ASPProgram()
    program.choose(Choice(P(x=RangePool(1, 2))))
    program.raw_asp(":~ p_wt(X).\n[1@0, X]\nq_wt(9).", predicates=[Q])
    rows = by_statement(program.ground().statement_profile())
    assert rows["q_wt(9)."].instances == 1


def test_existing_anon_variable_names_are_not_captured() -> None:
    # The reserved-name scan starts fresh indices past any ASPALCHEMY_ANON
    # already in the program, so a user's variable is never unified with a
    # renamed '_'
    P = Predicate.define("p_col", ["a", "b"])
    D = Predicate.define("d_col", ["a"])
    E = Predicate.define("e_col", ["a"])
    program = ASPProgram()
    program.fact(P(x := RangePool(1, 3), x))
    program.raw_asp(
        "d_col(ASPALCHEMY_ANON0) :- p_col(ASPALCHEMY_ANON0, _).\ne_col(A) :- p_col(A, _).",
        predicates=[D, E],
    )
    rows = by_statement(program.ground().statement_profile())
    assert rows["d_col(ASPALCHEMY_ANON0) :- p_col(ASPALCHEMY_ANON0, _)."].instances == 9
    assert rows["e_col(A) :- p_col(A, _)."].instances == 9


def test_aggregates_over_derived_atoms_are_an_upper_bound() -> None:
    # Documented limitation (docs: 'Profiling by statement'): a rule
    # derived purely from facts is open in the instrumented copy, so an
    # assignment aggregate over it grounds over its achievable range —
    # the profile charges an upper bound, not the single emitted rule
    Giv = Predicate.define("giv_da", ["x"])
    D = Predicate.define("d_da", ["x"])
    Total = Predicate.define("total_da", ["n"])
    program = ASPProgram()
    X, N = Variable("X"), Variable("N")
    program.fact(Giv(x=RangePool(1, 50)))
    program.when(Giv(x=X)).derive(D(x=X))
    program.when(N == Count(X, condition=D(x=X))).derive(Total(n=N))
    rows = by_statement(program.ground().statement_profile())
    aggregate_row = next(statement for statement in rows if "total_da" in statement)
    assert rows[aggregate_row].instances == 51  # pinned: upper bound, per the docs carve-out


def test_rename_and_weak_helper_edges() -> None:
    counter = itertools.count()
    # Suppression ends at a closing bracket below the negation's depth,
    # and at a separator on the same depth
    assert (
        _rename_anonymous("h :- #count{X : not p(X, _)} = 1, s(_)", counter)
        == "h :- #count{X : not p(X, _)} = 1, s(ASPALCHEMY_ANON0)"
    )
    assert _rename_anonymous("h :- not p(_), q(_)", counter) == "h :- not p(_), q(ASPALCHEMY_ANON1)"
    # Tail splitting and priority rewriting, string- and bracket-aware
    assert _split_weak_tail(':~ b("no tail here")') is None
    assert _rewrite_weak_priority('[1, "a,b@9", X]', 7) == '[1@7, "a,b@9", X]'
    assert _rewrite_weak_priority("[f(1,2), X]", 7) == "[f(1,2)@7, X]"
    assert _rewrite_weak_priority("[1@2]", 7) == "[1@7]"
    # The weight-segment scan skips string content (defensive: the API
    # never renders a string weight)
    assert _rewrite_weak_priority('["x@y", 1]', 7) == '["x@y"@7, 1]'
    assert _rewrite_weak_priority("[1@P, X]", 7) is None


def test_weak_explicit_priority_is_redirected() -> None:
    P = Predicate.define("p_ep", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(P(x=RangePool(1, 4))))
    program.penalize(P(x=X), weight=1, priority=2, terms=[X])
    rows = by_statement(program.ground().statement_profile())
    weak_row = next(statement for statement in rows if statement.startswith(":~"))
    assert "@2" in weak_row  # the ORIGINAL priority is reported in the row text
    assert rows[weak_row].instances == 4


def test_raw_bounded_choices_are_gated_not_companioned() -> None:
    # Round-4 regression: '1 { p } 2.' starts with a digit, so the
    # leading-brace test missed it and the companion wrapped a non-term,
    # crashing the profile. Any top-level brace now gates.
    P = Predicate.define("p_cb", ["x"])
    Q = Predicate.define("q_cb", ["x"])
    program = ASPProgram()
    program.raw_asp("1 { p_cb(1..3) } 2.\n2 <= { q_cb(1..2) }.", predicates=[P, Q])
    rows = by_statement(program.ground().statement_profile())
    assert rows["1 { p_cb(1..3) } 2."].instances == 1
    assert rows["2 <= { q_cb(1..2) }."].instances == 1


def test_multiline_raw_weak_tail_closes_the_continuation() -> None:
    # Round-4 regression: a multi-line raw weak ending in '[w@p]' left the
    # continuation open and swallowed the NEXT statement from the profile
    P = Predicate.define("p_mw", ["x"])
    Q = Predicate.define("q_mw", ["x"])
    program = ASPProgram()
    program.choose(Choice(P(x=RangePool(1, 2))))
    program.raw_asp(":~ p_mw(X),\n    p_mw(X). [1@0, X]\nq_mw(9).", predicates=[Q])
    rows = by_statement(program.ground().statement_profile())
    assert rows["q_mw(9)."].instances == 1
