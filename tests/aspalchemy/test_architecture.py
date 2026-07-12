"""
Architecture tests guarding the module DAG and import hygiene.

Every runtime intra-package import in aspalchemy/ must occur at module level
(deferred imports inside function bodies are banned, as they hide circular
dependencies), and the module-level import graph must be acyclic.
TYPE_CHECKING-guarded imports are ignored: they do not exist at runtime, and
they are the sanctioned mechanism for annotation-only upward references (e.g.
core's collect_predicates return type names Predicate, which core cannot
import at runtime).

Test modules in tests/aspalchemy are held to the same standard: all imports at
module top, of any module, not just intra-package ones.

Also home to the docs drift tripwire (see "Docs conventions" in the repo
CLAUDE.md): every ``__all__`` symbol must appear in docs/reference.md, and
that page's ``##`` sections must mirror the ``__all__`` category comments
(matched on each comment's first clause) in name and order.
"""

import ast
import re
import subprocess
from pathlib import Path

import aspalchemy

PACKAGE_DIR = Path(aspalchemy.__file__).resolve().parent
TESTS_DIR = Path(__file__).resolve().parent
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"


def _dep_of(node: ast.AST) -> str | None:
    """Return the aspalchemy submodule an import targets ('__init__' for the package), else None."""
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names if a.name.split(".")[0] == "aspalchemy"]
        target = names[0] if names else None
    elif isinstance(node, ast.ImportFrom):
        if node.level > 0:  # relative import within the package
            target = f"aspalchemy.{node.module}" if node.module else "aspalchemy"
        else:
            target = node.module if node.module and node.module.split(".")[0] == "aspalchemy" else None
    else:
        return None
    if target is None:
        return None
    parts = target.split(".")
    return parts[1] if len(parts) > 1 else "__init__"


def _is_type_checking_block(node: ast.AST) -> bool:
    test = node.test if isinstance(node, ast.If) else None
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _collect() -> tuple[dict[str, set[str]], list[str]]:
    graph: dict[str, set[str]] = {}
    deferred: list[str] = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        edges = graph.setdefault(path.stem, set())

        def scan(node: ast.AST, in_function: bool, path: Path = path, edges: set[str] = edges) -> None:
            for child in ast.iter_child_nodes(node):
                if _is_type_checking_block(child):
                    continue
                dep = _dep_of(child)
                if dep is not None:
                    if in_function:
                        deferred.append(f"{path}:{getattr(child, 'lineno', '?')}")
                    else:
                        edges.add(dep)
                scan(child, in_function or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)))

        scan(ast.parse(path.read_text(), filename=str(path)), in_function=False)
    return graph, deferred


def test_no_deferred_intra_package_imports() -> None:
    _, deferred = _collect()
    assert not deferred, "Deferred intra-package imports are banned:\n" + "\n".join(deferred)


def test_module_level_import_graph_is_acyclic() -> None:
    graph, _ = _collect()
    state: dict[str, int] = {}  # 0 = on current DFS path, 1 = fully explored

    def visit(module: str, stack: list[str]) -> None:
        if state.get(module) == 1 or module not in graph:
            return
        if state.get(module) == 0:
            cycle = [*stack[stack.index(module) :], module]
            raise AssertionError("Import cycle detected: " + " -> ".join(cycle))
        state[module] = 0
        for dep in sorted(graph[module]):
            visit(dep, [*stack, module])
        state[module] = 1

    for module in graph:
        visit(module, [])


def test_no_function_level_imports_in_tests() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("*.py")):

        def scan(node: ast.AST, in_function: bool, path: Path = path) -> None:
            for child in ast.iter_child_nodes(node):
                if _is_type_checking_block(child):
                    continue
                if in_function and isinstance(child, (ast.Import, ast.ImportFrom)):
                    offenders.append(f"{path}:{child.lineno}")
                scan(child, in_function or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)))

        scan(ast.parse(path.read_text(), filename=str(path)), in_function=False)
    assert not offenders, "Function-level imports are banned in tests:\n" + "\n".join(offenders)


def test_every_export_resolves() -> None:
    # __all__ is hand-maintained beside hand-maintained imports: a typo in
    # either direction only surfaces on `from aspalchemy import *` otherwise
    for name in aspalchemy.__all__:
        assert hasattr(aspalchemy, name), f"__all__ names {name}, but aspalchemy does not provide it"


def _package_defined_names() -> set[str]:
    """Every class and type-alias name defined at the top level of any package module."""
    names: set[str] = set()
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
                names.add(node.name.id)
    return names


def test_public_signatures_speak_exported_names() -> None:
    # The export rule, as a machine invariant instead of a review finding:
    # every package-defined type mentioned in a PUBLIC signature or return
    # annotation of an exported name must itself be exported — otherwise
    # users import it from a private module path, which freezes as de facto
    # API the day the package ships. Checked statically (annotations are
    # never evaluated, so TYPE_CHECKING-only names are fine).
    package_names = _package_defined_names()
    exported = set(aspalchemy.__all__)
    identifier = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    violations: list[str] = []

    def check_function(owner: str, func: ast.FunctionDef) -> None:
        annotations = [arg.annotation for arg in [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]]
        annotations.append(func.args.vararg.annotation if func.args.vararg else None)
        annotations.append(func.returns)
        for annotation in annotations:
            if annotation is None:
                continue
            for name in identifier.findall(ast.unparse(annotation)):
                if name in package_names and name not in exported:
                    violations.append(f"{owner}.{func.name}: {name}")

    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in exported:
                for member in node.body:
                    if isinstance(member, ast.FunctionDef) and not member.name.startswith("_"):
                        check_function(node.name, member)
            elif isinstance(node, ast.FunctionDef) and node.name in exported:
                check_function(path.stem, node)

    assert not violations, "unexported types in public signatures:\n" + "\n".join(sorted(set(violations)))


# The __all__ categories are deliberate; docs/reference.md mirrors them as its
# ## sections. These are the exact expected first clauses of the category
# comments in __init__.py — change a category and this test names every place
# that must move in the same commit.
EXPECTED_ALL_CATEGORIES = (
    "The program and its results",
    "Source locations",
    "Declaring predicates",
    "Rule-building objects",
    "Aggregates",
    "Rule-building utilities",
    "Hierarchy types",
    "Interop with raw clingo symbols",
    "Metadata",
)


def _all_category_first_clauses() -> list[str]:
    """First clause of each category comment in the ``__all__`` block, in order.

    A category comment is the first line of each run of consecutive comment
    lines inside the ``__all__`` list; its first clause is everything before
    a ``:`` or ``(`` (two comments are multi-clause or multi-line).
    """
    source = (PACKAGE_DIR / "__init__.py").read_text()
    match = re.search(r"^__all__ = \[.*?\n(.*?)^\]", source, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, "could not locate the __all__ block in __init__.py"
    clauses: list[str] = []
    previous_was_comment = False
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if not previous_was_comment:
                clauses.append(re.split(r"[:(]", stripped.lstrip("# "))[0].strip())
            previous_was_comment = True
        else:
            previous_was_comment = False
    return clauses


def test_reference_page_covers_every_export() -> None:
    # Drift tripwire (ARCHITECTURE.md §6): reference.md is the curated mirror
    # of __all__ — a new export that never lands on the page is drift.
    # A symbol counts as present when it appears as a code span, callables
    # optionally with trailing parens/decorator sugar: `pool`, `pool(...)`.
    text = (DOCS_DIR / "reference.md").read_text()
    missing = [name for name in aspalchemy.__all__ if not re.search(rf"`@?{re.escape(name)}[`(]", text)]
    assert not missing, "exported but absent from docs/reference.md: " + ", ".join(missing)


def test_reference_sections_mirror_all_categories() -> None:
    # Drift tripwire (ARCHITECTURE.md §6): both sides are pinned to the exact
    # expected strings above — the __init__.py category comments (by first
    # clause) and reference.md's ## sections, which must mirror them in name
    # and order after the opening "API stability" section.
    assert tuple(_all_category_first_clauses()) == EXPECTED_ALL_CATEGORIES, (
        "__all__ category comments drifted from the expected first clauses"
    )
    headings = re.findall(r"^## (.+)$", (DOCS_DIR / "reference.md").read_text(), flags=re.MULTILINE)
    assert headings and headings[0] == "API stability", "reference.md must open with the API stability section"
    assert tuple(headings[1:]) == EXPECTED_ALL_CATEGORIES, (
        "docs/reference.md ## sections drifted from the __all__ categories"
    )


def test_the_old_package_name_is_gone() -> None:
    # The 2026-07 rename: the package is aspalchemy. Its old name must not
    # regrow anywhere in the tracked tree — source, tests, docs, configs,
    # generated scripts. uv.lock is machine-generated (exempt).
    repo = Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True, cwd=repo
    ).stdout.splitlines()
    old_name = b"py" + b"clingo"  # assembled so this test does not flag itself
    offenders = [name for name in tracked if name != "uv.lock" and old_name in (repo / name).read_bytes().lower()]
    assert not offenders, f"the old package name has regrown in: {offenders}"
