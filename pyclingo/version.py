"""
Single source of truth for the version is pyproject.toml; this reads the
installed package metadata (uv_build does not support dynamic versions, so
the inversion runs this way).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pyclingo")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
