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
  expected output matches anything — the pin-the-fragment policy); a blank
  line inside expected output must be spelled <BLANKLINE>, so outputs
  containing blank lines usually read better as a text fence + assert.

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
            test = parser.get_doctest(block, namespace, doc, str(path), lineno)
            output: list[str] = []
            runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
            results = runner.run(test, out=output.append, clear_globs=False)
            # Names defined inside the doctest flow back to the page
            namespace.update(test.globs)
            if results.failed:
                pytest.fail("".join(output), pytrace=False)
        else:
            # Newline padding keeps traceback line numbers pointing at the
            # markdown file's real lines
            exec(compile("\n" * lineno + block, str(path), "exec"), namespace)
