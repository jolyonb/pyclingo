"""
Executes every python code block in pyclingo/README.md.

Blocks are concatenated in order and run in one shared namespace — they build on
each other, and this test is what keeps them cumulative and runnable.
"""

import re
from pathlib import Path

README = Path(__file__).parent.parent.parent / "pyclingo" / "README.md"


def test_readme_code_blocks_execute() -> None:
    text = README.read_text()
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)
    assert blocks, "no python code blocks found in README"

    source = "\n".join(blocks)
    exec(compile(source, str(README), "exec"), {})  # noqa: S102
