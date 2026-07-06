"""
Suite-wide fixtures.

Every ASP program rendered anywhere in the test suite is handed to clingo's
parser: text rendering can produce syntactically invalid output that a
render-string assertion happily pins, so "clingo accepts everything we
render" is enforced as an invariant rather than left to per-test diligence.
"""

import clingo.ast
import pytest

from pyclingo import ASPProgram


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


@pytest.fixture(autouse=True)
def rendered_programs_must_parse(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Parse-check the output of every ASPProgram.render() call in the suite.

    Tests that deliberately exercise invalid-program error handling can opt
    out with @pytest.mark.allow_invalid_render.
    """
    if request.node.get_closest_marker("allow_invalid_render"):
        return

    original_render = ASPProgram.render

    def checked_render(self: ASPProgram) -> str:
        output = original_render(self)
        assert_clingo_accepts(output)
        return output

    monkeypatch.setattr(ASPProgram, "render", checked_render)
