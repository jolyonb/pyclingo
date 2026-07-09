"""
Tests for pyclingo.version: __version__ is read from installed package
metadata, with a sentinel fallback when the package is not installed. This
pins the fallback string so an uninstalled source tree stays diagnosable.
"""

import importlib
import importlib.metadata

import pytest

import pyclingo.version as version_module


def test_version_falls_back_to_sentinel_when_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_not_found(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", raise_not_found)
    try:
        reloaded = importlib.reload(version_module)
        assert reloaded.__version__ == "0.0.0+unknown"
    finally:
        monkeypatch.undo()
        restored = importlib.reload(version_module)
        assert restored.__version__ != "0.0.0+unknown"
