"""
Executes every python code block in aspalchemy's markdown docs.

Documents are discovered, not listed: the repo README plus every top-level
docs/*.md — a new docs page is covered the day it lands. Per document,
blocks are concatenated in order and run in one shared namespace — they
build on each other, and this test is what keeps them cumulative and
runnable. A page with no python blocks skips (visibly, so a broken fence
can't silently drop a page's coverage).
"""

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
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)
    if not blocks:
        pytest.skip(f"no python code blocks in {doc}")

    source = "\n".join(blocks)
    exec(compile(source, str(path), "exec"), {})
