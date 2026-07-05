"""
Tests for clingo message parsing and severity handling.
"""

from pyclingo.clingo_handler import ClingoMessageHandler, LogLevel


def test_multiline_location_span_parses() -> None:
    # Location spans may cross lines (L:C-L:C); severity must still be read
    handler = ClingoMessageHandler("line one\nline two", stop_on_level=LogLevel.ERROR)
    handler.on_message(None, "<block>:1:10-2:5: error: something spans lines")  # type: ignore[arg-type]
    assert handler.highest_level == LogLevel.ERROR
    assert handler.should_halt


def test_single_line_span_parses() -> None:
    handler = ClingoMessageHandler("line one", stop_on_level=LogLevel.ERROR)
    handler.on_message(None, "<block>:1:3-7: warning: ordinary span")  # type: ignore[arg-type]
    assert handler.highest_level == LogLevel.WARNING
    assert not handler.should_halt
