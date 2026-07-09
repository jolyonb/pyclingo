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


def test_non_located_message_without_prefix_defaults_to_info() -> None:
    # No location span and no leading "word:" severity prefix: both regexes
    # fail, so severity falls back to "info" and the whole text is kept
    handler = ClingoMessageHandler("p(1).")
    handler.on_message(None, "plain message with no prefix")  # type: ignore[arg-type]
    assert handler.messages[0].severity == "info"
    assert handler.messages[0].message == "plain message with no prefix"


def test_format_all_messages_returns_none_when_empty() -> None:
    # With nothing captured, formatting yields None rather than a header block
    handler = ClingoMessageHandler("p(1).")
    assert handler.format_all_messages("solving") is None
