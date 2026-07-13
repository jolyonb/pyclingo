"""
Executes every python code block in aspalchemy's markdown docs.

Documents are discovered, not listed: the repo README plus every top-level
docs/*.md — a new docs page is covered the day it lands. Per document,
blocks run in order in one shared namespace — they build on each other,
and this test is what keeps them cumulative and runnable. A page with no
python blocks skips (visibly, so a broken fence can't silently drop a
page's coverage).

Two fence flavors, one namespace:
- Script fences (no prompts) exec as-is: the paste-and-run narrative form.
- Doctest fences (first line starts with >>>) run through doctest against
  the SAME namespace, so they see everything the page has built: the shown
  output is verified, not decorative. ELLIPSIS is on globally ("..." in
  expected output matches anything — the pin-the-fragment policy), and
  blank lines inside expected output are written as themselves: pages never
  spell <BLANKLINE>, because _mark_blank_lines puts the marker in for them
  (see below). A full program render — which always carries a blank line
  before its #show block — is therefore doctestable, and reads on the page
  exactly as it prints.

Failures land on real lines of the markdown file: script fences compile
with a line offset, and doctest examples carry the fence's position.
"""

import doctest
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
DOCUMENTS = [
    "README.md",
    *sorted(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "docs").glob("*.md")),
]


class _IgnoreTrailingBlanks(doctest.OutputChecker):
    """
    Ignore trailing blank lines in output.

    A fence cannot express them: a blank line at the end of an example just
    closes it, so there is nowhere to put the marker. print() of anything
    already newline-terminated (a program render) emits one, and pages
    should read the way a reader would type them — print(program.render()),
    not print(program.render(), end="").
    """

    def check_output(self, want: str, got: str, optionflags: int) -> bool:
        return super().check_output(want.rstrip() + "\n", got.rstrip() + "\n", optionflags)


def _mark_blank_lines(block: str) -> str:
    """
    Spell doctest's <BLANKLINE> marker for the page, so docs can show output
    exactly as it prints.

    doctest's PARSER ends an example's expected output at the first blank
    line — that is structural, not a flag — so a blank line inside output
    must be a marker. Requiring pages to write <BLANKLINE> would put a wart
    in the middle of the very output they exist to show, so the marker is
    inserted here instead.

    A blank line is expected output when the next non-blank line continues
    that output; a blank line before the next ">>>" is a separator between
    examples and stays blank. Trailing blanks end the block and stay blank.
    """
    lines = block.split("\n")
    for index, line in enumerate(lines):
        if line.strip():
            continue
        following = next((later for later in lines[index + 1 :] if later.strip()), None)
        if following is not None and not following.lstrip().startswith(">>>"):
            lines[index] = "<BLANKLINE>"
    return "\n".join(lines)


@pytest.mark.parametrize("doc", DOCUMENTS)
def test_doc_code_blocks_execute(doc: str) -> None:
    path = REPO_ROOT / doc
    text = path.read_text()
    matches = list(re.finditer(r"```python\n(.*?)```", text, flags=re.DOTALL))
    if not matches:
        pytest.skip(f"no python code blocks in {doc}")

    namespace: dict[str, object] = {}
    parser = doctest.DocTestParser()
    for match in matches:
        block = match.group(1)
        lineno = text[: match.start(1)].count("\n")
        if block.lstrip().startswith(">>>"):
            test = parser.get_doctest(_mark_blank_lines(block), namespace, doc, str(path), lineno)
            output: list[str] = []
            runner = doctest.DocTestRunner(checker=_IgnoreTrailingBlanks(), optionflags=doctest.ELLIPSIS)
            results = runner.run(test, out=output.append, clear_globs=False)
            # Names defined inside the doctest flow back to the page
            namespace.update(test.globs)
            if results.failed:
                pytest.fail("".join(output), pytrace=False)
        else:
            # Newline padding keeps traceback line numbers pointing at the
            # markdown file's real lines
            exec(compile("\n" * lineno + block, str(path), "exec"), namespace)
