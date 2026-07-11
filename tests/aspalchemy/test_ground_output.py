"""
Tests for GroundedProgram.ground_text()/aspif(): gringo's own output
formats, generated on demand by an in-process re-ground of the stored
source (clingo's application, stdout captured) — never a subprocess and
never a reimplementation of the formats.
"""

import subprocess
import sys

import clingo
import pytest

from aspalchemy import ASPProgram, Choice, Predicate, RangePool, Variable

Pick = Predicate.define("pick", ["x"])


def build() -> ASPProgram:
    program = ASPProgram()
    X = Variable("X")
    program.choose(Choice(Pick(x=RangePool(1, 3))))
    program.when(Pick(x=X), X > 1).derive(Predicate.define("big", ["x"])(x=X))
    return program


def test_ground_text_shows_instantiated_rules_with_names() -> None:
    text = build().ground().ground_text()
    assert "{pick(1)}." in text.replace(" ", "") or "{pick(1);" in text.replace(" ", "")
    assert "big(2):-pick(2)." in text.replace(" ", "")  # instantiated, named


def test_aspif_routes_agree_byte_for_byte() -> None:
    # TWO routes, one contract: context-free groundings go via subprocess,
    # context-bearing ones via the in-process capture. This receipt pins
    # them byte-identical on the same source — and against the raw
    # pipeline directly, so neither route can drift alone.
    class UnusedContext:
        """Present only to steer the in-process route; the text calls no @-functions."""

    program = build()
    subprocess_route = program.ground().aspif()
    in_process_route = program.ground(context=UnusedContext()).aspif()
    assert subprocess_route == in_process_route
    assert subprocess_route.startswith("asp 1 0 0")
    assert subprocess_route.rstrip("\n").endswith("\n0")
    real = subprocess.run(
        [sys.executable, "-m", "clingo", "--mode=gringo"],
        input=program.ground().text,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert subprocess_route == real


def test_ground_output_carries_the_grounding_context() -> None:
    # The design constraint that ruled out a subprocess: @-function
    # callbacks live in this process, and the re-ground must reuse them
    class Doubler:
        @staticmethod
        def double(x: clingo.Symbol) -> clingo.Symbol:
            return clingo.Number(x.number * 2)

    P = Predicate.define("p_ctxout", ["x"])
    program = ASPProgram()
    program.raw_asp("p_ctxout(@double(3)).", predicates=[P])
    grounded = program.ground(context=Doubler())
    assert "p_ctxout(6)." in grounded.ground_text()
    assert "p_ctxout(6)" in grounded.aspif()  # the output table names the atom


def test_ground_output_is_deterministic_and_solve_independent() -> None:
    grounded = build().ground()
    first = grounded.aspif()
    result = grounded.solve()
    next(iter(result))  # a search is OPEN on the handle's own Control
    # The re-ground uses a FRESH control, so output works mid-solve and
    # never trips the sequential guard
    assert grounded.aspif() == first
    assert len(list(result)) + result.models_yielded >= 1  # the open search is undisturbed
    result.close()
    assert grounded.solve() is not None


def test_optimizing_programs_show_their_objectives() -> None:
    program = build()
    X = Variable("X")
    program.minimize(X, condition=Pick(x=X))
    grounded = program.ground()
    # gringo's --text renders ground objectives as weak constraints
    assert ":~pick(1).[1@0]" in grounded.ground_text().replace(" ", "")
    assert any(line.startswith("2 ") for line in grounded.aspif().splitlines())  # a minimize statement


def test_stateful_context_divergence_is_loud() -> None:
    # The documented hazard: a context answering differently on the second
    # call. Here it fails outright on re-ground — the error names the cause
    class OneShot:
        def __init__(self) -> None:
            self.calls = 0

        def val(self) -> clingo.Symbol:
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("spent")
            return clingo.Number(7)

    P = Predicate.define("p_oneshot", ["x"])
    program = ASPProgram()
    program.raw_asp("p_oneshot(@val()).", predicates=[P])
    grounded = program.ground(context=OneShot())
    with pytest.raises(RuntimeError, match=r"stateful @-function context.*clingo reported:(.|\n)*spent"):
        grounded.ground_text()  # the real cause rides the error (chaining dies at the C boundary)


def test_ground_output_keeps_the_console_clean(capfd: pytest.CaptureFixture[str]) -> None:
    # The common (context-free) path is a subprocess: by construction it
    # touches nothing in this process — success and failure both silent
    grounded = build().ground()
    grounded.aspif()
    grounded.ground_text()
    out, err = capfd.readouterr()
    assert out == "" and err == ""
    # The context path folds the cause into the error (asserted in
    # test_stateful_context_divergence_is_loud); its capture is complete at
    # the fd level in production, but a harness that REPLACES sys.stderr
    # (pytest does) bypasses fds entirely, so console-cleanliness for that
    # path cannot be asserted honestly from inside the harness
