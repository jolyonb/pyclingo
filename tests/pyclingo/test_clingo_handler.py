"""
Tests for clingo message parsing and severity handling.
"""

import clingo

from pyclingo import LogLevel
from pyclingo.clingo_handler import ClingoMessageHandler


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


def test_multiline_message_payload_preserved() -> None:
    # gringo message payloads can span lines; the parse must not truncate them
    handler = ClingoMessageHandler("p(1).")
    handler.on_message(
        clingo.MessageCode.AtomUndefined,
        "<string>:1:1-5: info: atom does not occur in any rule head:\n  q(X)",
    )
    assert "q(X)" in handler.messages[0].message
