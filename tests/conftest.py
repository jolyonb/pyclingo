"""
Suite-wide fixtures.

Every ASP program rendered anywhere in the test suite is handed to clingo's
parser, and every TOP-LEVEL term render (a test directly asserting a term's
string) is wrapped in a minimal host statement and parsed too: text rendering
can produce syntactically invalid output that a render-string assertion
happily pins , so "clingo accepts everything we render" is enforced as an
invariant rather than left to per-test diligence.

Tests that deliberately exercise invalid-program error handling can opt out
with @pytest.mark.allow_invalid_render.
"""

from collections.abc import Callable
from typing import Any

import clingo.ast
import pytest

from pyclingo import (
    Aggregate,
    ASPProgram,
    Choice,
    Comparison,
    ConditionalLiteral,
    DefaultNegation,
    Expression,
    Pool,
    Predicate,
    Value,
)


def assert_clingo_accepts(program_text: str) -> None:
    """Fail if clingo's parser rejects the program text."""
    errors: list[str] = []
    try:
        clingo.ast.parse_string(
            program_text,
            lambda statement: None,
            logger=lambda code, message: errors.append(message),
        )
    except RuntimeError as e:
        detail = "\n".join(errors) or str(e)
        pytest.fail(f"Rendered program is not valid clingo:\n{detail}\n\n--- program ---\n{program_text}")


# Each term class knows its legal position; wrap a rendered fragment in a
# minimal host statement there so the parser can judge it. (parse_string
# checks syntax only — ungrounded fragments like "p(X)." are fine.)
_TERM_HOSTS: list[tuple[Any, Callable[[str], str]]] = [
    (Choice, lambda t: f"{t}."),
    (Predicate, lambda t: f"{t}."),
    (Aggregate, lambda t: f"x :- {t} > 0."),
    (Comparison, lambda t: f"x :- {t}."),
    (DefaultNegation, lambda t: f"x :- {t}."),
    (ConditionalLiteral, lambda t: f"x :- {t}."),
    (Expression, lambda t: f"x({t})."),
    (Value, lambda t: f"x({t})."),
    (Pool, lambda t: f"x({t})."),
]


@pytest.fixture(autouse=True)
def rendered_programs_must_parse(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Parse-check every ASPProgram.render() and every top-level term render.

    A depth guard keeps nested renders free: rendering a program (or a
    composite term) recursively renders its parts, which the outermost parse
    already covers in context — only the outermost call pays.
    """
    if request.node.get_closest_marker("allow_invalid_render"):
        return

    depth = [0]

    original_program_render = ASPProgram.render

    def checked_program_render(self: ASPProgram, *args: Any, **kwargs: Any) -> str:
        depth[0] += 1
        try:
            output = original_program_render(self, *args, **kwargs)
        finally:
            depth[0] -= 1
        if depth[0] == 0:
            assert_clingo_accepts(output)
        return output

    monkeypatch.setattr(ASPProgram, "render", checked_program_render)

    for term_class, host in _TERM_HOSTS:
        original = term_class.render

        def checked_render(
            self: Any,
            *args: Any,
            _original: Callable[..., str] = original,
            _host: Callable[[str], str] = host,
            **kwargs: Any,
        ) -> str:
            depth[0] += 1
            try:
                output = _original(self, *args, **kwargs)
            finally:
                depth[0] -= 1
            if depth[0] == 0:
                assert_clingo_accepts(_host(output))
            return output

        monkeypatch.setattr(term_class, "render", checked_render)
