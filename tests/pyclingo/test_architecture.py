"""
Architecture tests guarding the module DAG and import hygiene.

Every runtime intra-package import in pyclingo/ must occur at module level
(deferred imports inside function bodies are banned, as they hide circular
dependencies), and the module-level import graph must be acyclic.
TYPE_CHECKING-guarded imports are ignored: they do not exist at runtime, and
they are the sanctioned mechanism for annotation-only upward references (e.g.
core's collect_predicates return type names Predicate, which core cannot
import at runtime).

Test modules in tests/pyclingo are held to the same standard: all imports at
module top, of any module, not just intra-package ones.
"""

import ast
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "pyclingo"
TESTS_DIR = Path(__file__).resolve().parent


def _dep_of(node: ast.AST) -> str | None:
    """Return the pyclingo submodule an import targets ('__init__' for the package), else None."""
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names if a.name.split(".")[0] == "pyclingo"]
        target = names[0] if names else None
    elif isinstance(node, ast.ImportFrom):
        if node.level > 0:  # relative import within the package
            target = f"pyclingo.{node.module}" if node.module else "pyclingo"
        else:
            target = node.module if node.module and node.module.split(".")[0] == "pyclingo" else None
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
