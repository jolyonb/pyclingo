"""
Source locations: the line of user Python that authored a program element.

capture_location() walks the call stack outward past library frames and
records (filename, lineno) of the first frame belonging to user code.
Plumbing is declared three orthogonal ways: by dotted module prefix
(pyclingo itself, plus register_skip_package() — a whole package or a
single module), by code object (the @attribute_to_caller decorator, one
function), or by fiat (location_override(), when no stack frame is the
honest answer). Helpers, lambdas, and comprehensions inside a skipped
module are all plumbing. Capture reads a few frame attributes and never
touches source files; formatting happens only when a diagnostic needs it.
"""

import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import CodeType, FrameType


@dataclass(frozen=True)
class SourceLocation:
    """A point in user source: the filename as the frame recorded it, and a 1-based line."""

    filename: str
    lineno: int

    def display(self) -> str:
        """
        path:line, relative to the working directory when it lies inside it.
        Always one line: a newline in the filename (compile() accepts any
        string) is escaped, so consumers may embed the result in line-
        oriented output — an annotated render must not gain lines.
        """
        try:
            relative = os.path.relpath(self.filename)
        except ValueError:  # pragma: no cover — only Windows raises here (path on a different drive)
            relative = self.filename
        path = self.filename if relative.startswith("..") else relative
        path = path.replace("\r", "\\r").replace("\n", "\\n")
        return f"{path}:{self.lineno}"


# Copy-on-write: registration rebinds a fresh frozenset, so a walker
# iterating on another thread sees the old set or the new one, never a
# mutating one ("Set changed size during iteration" out of an innocent
# fact() call)
_skip_prefixes: frozenset[str] = frozenset({"pyclingo"})
# Keyed by identity, holding the code object alive: two functions compiled
# from identical source in different files have EQUAL code objects (CPython
# code equality ignores the filename), and marking one must not mark the other
_skip_code_objects: dict[int, CodeType] = {}

_override: ContextVar[SourceLocation | None] = ContextVar("pyclingo_location_override", default=None)


def register_skip_package(name: str) -> None:
    """
    Mark a package or module, by dotted name, as plumbing: capture_location()
    walks past frames whose module is the name or lives under it. A framework
    built on pyclingo registers itself ("myfw") so captured locations point at
    ITS caller's code; a framework whose package also contains authored code
    registers just its plumbing modules ("myfw.core", "myfw.solvers.base"),
    leaving the authored modules' lines intact.

    Registration is process-wide and permanent: register only names you own.
    "__main__" is rejected — that is the user's own script, never plumbing.
    """
    global _skip_prefixes
    parts = name.split(".") if isinstance(name, str) else []
    if not parts or not all(part.isidentifier() for part in parts):
        raise ValueError(f"Package name must be a dotted module path, got {name!r}")
    if "__main__" in parts:
        raise ValueError("Cannot register '__main__' as plumbing: it is the user's own script")
    _skip_prefixes = _skip_prefixes | {name}


def attribute_to_caller[F: Callable[..., object]](func: F) -> F:
    """
    Mark one function as plumbing: capture_location() walks past its
    frames, so statements it makes are attributed to its caller. For a
    helper that emits rules on the caller's behalf — the interesting line
    is the call site, not the helper's interior.

    The mark is per code object: lambdas and comprehensions defined inside
    the function are not covered (register_skip_package() skips a whole
    module, those included).
    """
    code = getattr(func, "__code__", None)
    if code is None:
        raise TypeError(
            f"attribute_to_caller() takes a plain function, got {type(func).__name__}; "
            f"apply it closest to the def, below @classmethod/@staticmethod"
        )
    _skip_code_objects[id(code)] = code
    return func


@contextmanager
def location_override(location: SourceLocation) -> Iterator[None]:
    """
    Attribute every element created in the block to the given location
    instead of walking the stack. For code emitting rules where no stack
    frame is the honest answer — e.g. a framework module emitting during a
    finalize pass, where the meaningful location is the module's own
    construction site, captured earlier.
    """
    if not isinstance(location, SourceLocation):
        raise TypeError(f"location_override() takes a SourceLocation, got {type(location).__name__}")
    token = _override.set(location)
    try:
        yield
    finally:
        _override.reset(token)


def _module_is_plumbing(module_name: object) -> bool:
    """True when the module name equals a registered prefix or lives under one."""
    if not isinstance(module_name, str):
        return False
    return any(module_name == prefix or module_name.startswith(prefix + ".") for prefix in _skip_prefixes)


def capture_location() -> SourceLocation | None:
    """
    The first stack frame outward that is not plumbing, as a
    SourceLocation — or the active location_override(), or None if every
    frame is plumbing.
    """
    override = _override.get()
    if override is not None:
        return override
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename
        # A non-string __name__ (exec with hand-built globals) is not
        # identifiable as plumbing, so it counts as user code. Frozen
        # interpreter frames (import machinery) are never user code: skip
        # them, so an import-time statement lands on the importing line.
        if (
            not _module_is_plumbing(frame.f_globals.get("__name__"))
            and id(frame.f_code) not in _skip_code_objects
            and not filename.startswith("<frozen")
        ):
            return SourceLocation(filename, frame.f_lineno)
        frame = frame.f_back
    return None
