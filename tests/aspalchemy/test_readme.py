"""
Executes every python code block in aspalchemy's markdown docs.

Per document, blocks are concatenated in order and run in one shared
namespace — they build on each other, and this test is what keeps them
cumulative and runnable.
"""

import re
from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
DOCUMENTS = ["README.md", "MATH.md"]


@pytest.mark.parametrize("doc", DOCUMENTS)
def test_doc_code_blocks_execute(doc: str) -> None:
    path = DOCS_DIR / doc
    text = path.read_text()
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)
    assert blocks, f"no python code blocks found in {doc}"

    source = "\n".join(blocks)
    exec(compile(source, str(path), "exec"), {})
