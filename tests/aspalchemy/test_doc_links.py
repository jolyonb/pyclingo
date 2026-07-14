"""
Checks every internal link in aspalchemy's markdown docs.

The site is a web of cross-references — one home page per topic, everything
else links to it — and two kinds of rot are invisible until a reader clicks:
a renamed FILE (the link 404s) and a renamed HEADING (the link lands on the
page but not the section, silently scrolling nowhere). Anchors are kramdown
auto-ids, generated from the heading text, so editing prose that happens to
be a heading is enough to break an inbound link from another page.

So: for every relative link in the README and docs/*.md, the target file must
exist, and its #fragment must name a heading that is actually there. Link
targets are resolved the way Jekyll resolves them (relative .md paths, per
jekyll-relative-links), and the sidebar nav — the one place that links to
built .html pages instead — is checked against the pages on disk too.

Links and headings are both read from OUTSIDE fenced code blocks: a fence can
hold ASP comments that open with "#" (a heading, to a naive parser) and
markdown that is being displayed rather than followed.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
DOCS = REPO_ROOT / "docs"
DOCUMENTS = [
    "README.md",
    *sorted(p.relative_to(REPO_ROOT).as_posix() for p in DOCS.glob("*.md")),
]

_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# The layout links to built pages: href="{{ "/rules.html" | relative_url }}"
_NAV_LINK = re.compile(r'"/([\w-]+)\.html"')


def _prose(text: str) -> str:
    """The document with fenced code blocks blanked out, lines preserved."""
    return _FENCE.sub(lambda m: "\n" * m.group().count("\n"), text)


def _kramdown_id(heading: str) -> str:
    """
    The anchor kramdown generates for a heading — its auto_ids algorithm.

    Leading non-letters go, then every character outside [a-zA-Z0-9 _-] is
    DELETED (not replaced), spaces become hyphens, and the result is
    lowercased. Deleting rather than replacing is why "Choose: exactly one
    color" is #choose-exactly-one-color and not #choose--exactly-one-color:
    the colon vanishes and its neighbouring space carries the hyphen. The
    underscore survives, which is what makes "## raw_asp(): verbatim clingo"
    reachable at #raw_asp-verbatim-clingo.
    """
    generated = re.sub(r"^[^a-zA-Z]+", "", heading)
    generated = re.sub(r"[^a-zA-Z0-9 _-]", "", generated)
    generated = generated.replace(" ", "-").lower()
    return generated or "section"


def _anchors(text: str) -> set[str]:
    """Every anchor a reader can link to in this document."""
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for _, heading in _HEADING.findall(_prose(text)):
        base = _kramdown_id(heading)
        # kramdown disambiguates repeats by suffixing a counter
        anchors.add(base if base not in seen else f"{base}-{seen[base]}")
        seen[base] = seen.get(base, 0) + 1
    return anchors


@pytest.mark.parametrize("doc", DOCUMENTS)
def test_internal_links_resolve(doc: str) -> None:
    path = REPO_ROOT / doc
    text = path.read_text()
    prose = _prose(text)

    for match in _LINK.finditer(prose):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue  # external; not ours to keep alive
        line = prose[: match.start()].count("\n") + 1
        where = f"{doc}:{line}"

        file_part, _, fragment = target.partition("#")
        if file_part:
            resolved = (path.parent / file_part).resolve()
            assert resolved.is_file(), f"{where}: link target does not exist: {target}"
            assert resolved.suffix == ".md", f"{where}: link to a non-markdown file: {target}"
        else:
            resolved = path  # a bare #fragment: same page

        if not fragment:
            continue
        anchors = _anchors(resolved.read_text())
        assert fragment in anchors, (
            f"{where}: link points at #{fragment}, which is not a heading in "
            f"{resolved.relative_to(REPO_ROOT)}. Anchors are generated from heading TEXT, so "
            f"renaming a heading breaks every inbound link to it — fix the link, or restore the "
            f"heading. Anchors that page does have: {sorted(anchors)}"
        )


def test_sidebar_nav_pages_exist() -> None:
    """The nav lives in the layout, so a renamed page rots it from a distance."""
    layout = (DOCS / "_layouts" / "default.html").read_text()
    for page in _NAV_LINK.findall(layout):
        source = DOCS / f"{page}.md"
        assert source.is_file(), (
            f"docs/_layouts/default.html: the nav links to /{page}.html, but there is no "
            f"docs/{page}.md to build it from."
        )
