"""
Tests for pyclingo.source_location: capture_location()'s stack walk and
skip registry, location_override(), and SourceLocation.display().
Expected line numbers are captured at runtime via inspect, never as
literals.
"""

import inspect
import os
import sys
from collections.abc import Iterator
from types import FrameType
from typing import Any

import pytest

from pyclingo import (
    ASPProgram,
    Predicate,
    SourceLocation,
    attribute_to_caller,
    location_override,
    register_skip_package,
)
from pyclingo import source_location as source_location_module
from pyclingo.source_location import capture_location

P = Predicate.define("p_loc", ["x"])

_frame = inspect.currentframe()
assert _frame is not None
THIS_FILE = _frame.f_code.co_filename
del _frame


@pytest.fixture
def skip_registry() -> Iterator[None]:
    """Snapshot the skip-prefix registry and restore it after the test."""
    snapshot = set(source_location_module._skip_prefixes)
    yield
    source_location_module._skip_prefixes.clear()
    source_location_module._skip_prefixes.update(snapshot)


# ---- capture_location ----


def test_capture_location_returns_caller_file_and_line() -> None:
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    location = capture_location()  # lineno + 1
    assert location == SourceLocation(THIS_FILE, lineno + 1)


def test_fact_stamps_element_with_authoring_line() -> None:
    program = ASPProgram()
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    program.fact(P(x=1))  # lineno + 1
    element = next(iter(program["Rules"]))
    assert element.source_location == SourceLocation(THIS_FILE, lineno + 1)


def test_lambda_in_caller_yields_caller_location() -> None:
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    location = (lambda: capture_location())()  # lineno + 1
    assert location == SourceLocation(THIS_FILE, lineno + 1)


def test_comprehension_in_caller_yields_caller_location() -> None:
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    locations = [capture_location() for _ in range(2)]  # lineno + 1
    assert locations == [SourceLocation(THIS_FILE, lineno + 1)] * 2


def test_non_string_dunder_name_counts_as_user_code() -> None:
    # exec with hand-built globals can carry a non-string __name__; such a
    # frame is not identifiable as plumbing, so it counts as user code
    captured: dict[str, SourceLocation | None] = {}
    code = compile("captured['loc'] = capture_location()", "<plugin>", "exec")
    exec(code, {"__name__": None, "capture_location": capture_location, "captured": captured})
    assert captured["loc"] == SourceLocation("<plugin>", 1)


def test_frozen_interpreter_frames_are_skipped() -> None:
    # Import-machinery frames render as "<frozen ...>" and are never user
    # code: the walk continues past them to the line that triggered them
    captured: dict[str, SourceLocation | None] = {}
    code = compile("captured['loc'] = capture_location()", "<frozen fakeboot>", "exec")
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    exec(code, {"__name__": "fakeboot", "capture_location": capture_location, "captured": captured})  # lineno + 1
    assert captured["loc"] == SourceLocation(THIS_FILE, lineno + 1)


def test_capture_returns_none_when_every_frame_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    packages: set[str] = {"pyclingo"}
    frame: FrameType | None = sys._getframe()
    while frame is not None:
        packages.add(frame.f_globals.get("__name__", "").partition(".")[0])
        frame = frame.f_back
    monkeypatch.setattr(source_location_module, "_skip_prefixes", packages)
    assert capture_location() is None


# ---- register_skip_package ----


def test_register_skip_package_rejects_malformed_paths() -> None:
    with pytest.raises(ValueError, match="must be a dotted module path"):
        register_skip_package("fake..pkg")  # empty segment
    with pytest.raises(ValueError, match="must be a dotted module path"):
        register_skip_package("")
    with pytest.raises(ValueError, match="must be a dotted module path"):
        register_skip_package(123)  # type: ignore[arg-type]


def test_register_skip_package_rejects_main() -> None:
    # A too-broad registration silently destroys all attribution; "__main__"
    # is the user's own script, so it is refused outright
    with pytest.raises(ValueError, match="user's own script"):
        register_skip_package("__main__")
    with pytest.raises(ValueError, match="user's own script"):
        register_skip_package("somefw.__main__")


def test_dotted_prefix_skips_one_module_but_not_its_siblings(skip_registry: None) -> None:
    # Registering "somefw.core" marks that module (and anything under it) as
    # plumbing while siblings — authored code in the same package — and the
    # parent package itself keep their lines
    def globals_for(module_name: str, captured: dict[str, SourceLocation | None]) -> dict[str, Any]:
        return {"__name__": module_name, "capture_location": capture_location, "captured": captured}

    source = "captured['loc'] = capture_location()"
    captured: dict[str, SourceLocation | None] = {}
    register_skip_package("somefw.core")

    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    exec(compile(source, "<core>", "exec"), globals_for("somefw.core", captured))  # lineno + 1
    assert captured["loc"] == SourceLocation(THIS_FILE, lineno + 1)  # skipped: lands on the exec line
    exec(compile(source, "<grids>", "exec"), globals_for("somefw.core.grids", captured))  # lineno + 3
    assert captured["loc"] == SourceLocation(THIS_FILE, lineno + 3)  # under the prefix: also skipped

    exec(compile(source, "<solvers>", "exec"), globals_for("somefw.solvers", captured))
    assert captured["loc"] == SourceLocation("<solvers>", 1)  # sibling keeps its line
    exec(compile(source, "<pkg>", "exec"), globals_for("somefw", captured))
    assert captured["loc"] == SourceLocation("<pkg>", 1)  # parent package is not covered either


def test_registered_package_frames_are_skipped(skip_registry: None) -> None:
    source = "captured['loc'] = capture_location()"
    captured: dict[str, SourceLocation | None] = {}
    fake_globals: dict[str, Any] = {
        "__name__": "fakepkg.mod",
        "capture_location": capture_location,
        "captured": captured,
    }
    code = compile(source, "<fakepkg>", "exec")

    exec(code, fake_globals)  # fakepkg is not yet registered: the exec frame is user code
    assert captured["loc"] == SourceLocation("<fakepkg>", 1)

    register_skip_package("fakepkg")
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    exec(code, fake_globals)  # lineno + 1: the fakepkg frame is skipped, landing here
    assert captured["loc"] == SourceLocation(THIS_FILE, lineno + 1)


# ---- attribute_to_caller ----


def test_attribute_to_caller_helper_attributes_to_its_caller() -> None:
    program = ASPProgram()

    @attribute_to_caller
    def add_fact(prog: ASPProgram) -> None:
        prog.fact(P(x=7))  # plumbing: the walk passes through

    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    add_fact(program)  # lineno + 1
    element = next(iter(program["Rules"]))
    assert element.source_location == SourceLocation(THIS_FILE, lineno + 1)


def test_attribute_to_caller_rejects_wrapped_callables() -> None:
    # classmethod/staticmethod objects and partials carry no __code__; the
    # error says where the decorator belongs instead of an AttributeError
    with pytest.raises(TypeError, match="closest to the def"):
        attribute_to_caller(classmethod(lambda cls: None))  # type: ignore[type-var]


def test_attribute_to_caller_marks_by_identity_not_equality() -> None:
    # Two functions compiled from identical source in different "files" have
    # EQUAL code objects (CPython ignores the filename); marking one must
    # not mark the other
    source = "def helper(captured):\n    captured['loc'] = capture_location()"
    namespace_a: dict[str, Any] = {"capture_location": capture_location}
    namespace_b: dict[str, Any] = {"capture_location": capture_location}
    exec(compile(source, "<file_a>", "exec"), namespace_a)
    exec(compile(source, "<file_b>", "exec"), namespace_b)
    assert namespace_a["helper"].__code__ == namespace_b["helper"].__code__  # the trap

    attribute_to_caller(namespace_a["helper"])
    captured: dict[str, SourceLocation | None] = {}
    frame = inspect.currentframe()
    assert frame is not None
    lineno = frame.f_lineno
    namespace_a["helper"](captured)  # lineno + 1: marked, attributes here
    assert captured["loc"] == SourceLocation(THIS_FILE, lineno + 1)
    namespace_b["helper"](captured)  # unmarked twin keeps its own interior line
    assert captured["loc"] == SourceLocation("<file_b>", 2)


def test_undecorated_helper_attributes_to_its_interior() -> None:
    # The contrast case: without the mark, the helper's own line answers
    program = ASPProgram()

    def add_fact(prog: ASPProgram) -> int:
        frame = inspect.currentframe()
        assert frame is not None
        lineno = frame.f_lineno
        prog.fact(P(x=8))  # lineno + 1
        return lineno + 1

    fact_line = add_fact(program)
    element = next(iter(program["Rules"]))
    assert element.source_location == SourceLocation(THIS_FILE, fact_line)


# ---- location_override ----


def test_location_override_short_circuits_capture() -> None:
    override = SourceLocation("framework.py", 42)
    with location_override(override):
        assert capture_location() == override


def test_location_override_stamps_elements_in_block() -> None:
    override = SourceLocation("framework.py", 42)
    program = ASPProgram()
    with location_override(override):
        program.fact(P(x=1))
    element = next(iter(program["Rules"]))
    assert element.source_location == override


def test_location_override_nests_and_restores() -> None:
    outer = SourceLocation("outer.py", 1)
    inner = SourceLocation("inner.py", 2)
    with location_override(outer):
        assert capture_location() == outer
        with location_override(inner):
            assert capture_location() == inner
        assert capture_location() == outer
    location = capture_location()
    assert location is not None
    assert location.filename == THIS_FILE


def test_location_override_restores_on_exception() -> None:
    override = SourceLocation("boom.py", 9)
    with pytest.raises(RuntimeError, match="boom"), location_override(override):
        raise RuntimeError("boom")
    location = capture_location()
    assert location is not None
    assert location.filename == THIS_FILE


def test_location_override_rejects_non_source_location() -> None:
    with pytest.raises(TypeError, match="takes a SourceLocation, got tuple"), location_override(("x.py", 3)):  # type: ignore[arg-type]
        pass


# ---- SourceLocation.display ----


def test_display_is_relative_inside_cwd() -> None:
    absolute = os.path.join(os.getcwd(), "tests", "sample.py")
    assert SourceLocation(absolute, 12).display() == os.path.join("tests", "sample.py") + ":12"


def test_display_keeps_absolute_path_outside_cwd() -> None:
    assert SourceLocation("/elsewhere/x.py", 3).display() == "/elsewhere/x.py:3"


def test_display_passes_through_synthetic_filenames() -> None:
    assert SourceLocation("<string>", 1).display() == "<string>:1"


def test_display_escapes_newlines() -> None:
    # compile() accepts any string as a filename; display() must stay one
    # line so an annotated render never gains lines (or injects statements)
    assert SourceLocation("evil\nq(666).", 1).display() == "evil\\nq(666).:1"
    assert SourceLocation("evil\rq(7).", 2).display() == "evil\\rq(7).:2"
