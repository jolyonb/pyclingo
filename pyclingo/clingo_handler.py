import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum

import clingo

from pyclingo.source_location import SourceLocation


class LogLevel(IntEnum):
    """
    Log levels for Clingo messages. clingo emits only info/warning/error;
    CRITICAL exists as a stop_on_log_level threshold meaning "never halt".
    """

    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40

    @classmethod
    def from_string(cls, level_str: str) -> LogLevel:
        """Convert Clingo's string levels to our enum (unknown words read as INFO)."""
        mapping = {
            "info": cls.INFO,
            "warning": cls.WARNING,
            "error": cls.ERROR,
        }
        return mapping.get(level_str.lower(), cls.INFO)


@dataclass(frozen=True)
class ClingoMessage:
    """Represents a parsed Clingo warning/error message."""

    filename: str
    line: int
    code: clingo.MessageCode
    column_start: int
    column_end: int
    severity: LogLevel
    message: str
    raw_message: str


class ClingoMessageHandler:
    """Handles capturing and formatting of Clingo messages."""

    def __init__(
        self,
        asp_source: str,
        stop_on_level: LogLevel = LogLevel.INFO,
        line_origins: Mapping[int, SourceLocation] | None = None,
    ):
        """line_origins maps 1-based ASP source lines to the user Python line that authored them."""
        self.messages: list[ClingoMessage] = []
        # split("\n"), not splitlines(): gringo's line numbers (and the
        # line_origins map) count newlines only, so a lone \r inside raw
        # text must not shift the displayed context
        self._asp_lines: list[str] = asp_source.split("\n")
        self.stop_on_level = stop_on_level
        self._line_origins: Mapping[int, SourceLocation] = line_origins or {}
        self._highest_level: LogLevel | None = None

    def on_message(self, code: clingo.MessageCode, message: str) -> None:
        """Callback for Clingo messages."""
        # Location spans may be single-line (L:C-C) or multi-line (L:C-L:C).
        # DOTALL: the message payload itself may span lines (e.g. "no atoms
        # over signature occur in program:\n  -p/1")
        if location_match := re.match(r"<(.+?)>:(\d+):(\d+)-(?:\d+:)?(\d+):\s*(.+?):\s*(.+)", message, re.DOTALL):
            severity = LogLevel.from_string(location_match[5])
            parsed_msg = ClingoMessage(
                filename=location_match[1],
                line=int(location_match[2]),
                code=code,
                column_start=int(location_match[3]),
                column_end=int(location_match[4]),
                severity=severity,
                message=location_match[6],
                raw_message=message,
            )
            self.messages.append(parsed_msg)
        else:
            if level_match := re.match(r"^(\w+):\s*(.+)", message):
                severity = LogLevel.from_string(level_match[1])
                message_text = level_match[2]
            else:
                severity = LogLevel.INFO
                message_text = message

            self.messages.append(
                ClingoMessage(
                    filename="<unknown>",
                    line=0,
                    code=code,
                    column_start=0,
                    column_end=0,
                    severity=severity,
                    message=message_text,
                    raw_message=message,
                )
            )

        # Update highest log level
        if self._highest_level is None or severity > self._highest_level:
            self._highest_level = severity

    @property
    def highest_level(self) -> LogLevel | None:
        """Get the highest log level encountered."""
        return self._highest_level

    @property
    def should_halt(self) -> bool:
        """Determine if execution should halt based on log levels."""
        if self._highest_level is None:
            return False
        return self._highest_level >= self.stop_on_level

    def format_message(self, msg: ClingoMessage) -> str:
        """Format a single message with context."""
        output = [
            f"{msg.severity.name}: {msg.message}",
            f"  at line {msg.line}, columns {msg.column_start}-{msg.column_end}",
            "",
            f"  in {msg.filename}",
        ]

        # Show the problematic line with context
        if 0 < msg.line <= len(self._asp_lines):
            # Show line before (if exists)
            if msg.line > 1:
                output.append(f"{msg.line - 1:4d} | {self._asp_lines[msg.line - 2]}")

            # Show the problematic line
            problem_line = self._asp_lines[msg.line - 1]
            output.append(f"{msg.line:4d} | {problem_line}")

            # Add the error pointer - single caret at the start position
            if msg.column_start > 0:
                # The column_start is 1-based, but we need 0-based for the string
                pointer_pos = msg.column_start - 1
                # Multi-line spans keep column_end from the later line, which can be
                # smaller than column_start; always draw at least one caret
                pointer = " " * pointer_pos + "^" * max(1, msg.column_end - msg.column_start)
                output.append(f"       {pointer}")

        # Close the loop back to Python: the ASP line knows which user line
        # authored it, so even errors only gringo can catch land on source.
        # A parse error can cascade past a malformed statement onto generated
        # framing text (e.g. a raw block missing its final "." errors at the
        # next token); the nearest mapped line above is the best lead
        if origin := self._line_origins.get(msg.line):
            output.append(f"  generated by {origin.display()}")
        elif preceding := self._nearest_preceding_origin(msg.line):
            output.append(f"  generated after {preceding.display()}")

        output.append("")
        return "\n".join(output)

    def _nearest_preceding_origin(self, line: int) -> SourceLocation | None:
        """The origin of the closest mapped line above, if any."""
        candidates = [mapped for mapped in self._line_origins if mapped < line]
        return self._line_origins[max(candidates)] if candidates else None

    def format_all_messages(self, verb: str) -> str | None:
        """Format all captured messages."""
        if not self.messages:
            return None

        output = [
            "-" * 60,
            f"Found {len(self.messages)} message{'s' if len(self.messages) > 1 else ''} during {verb}:\n",
        ]
        for msg in self.messages:
            output.extend(
                [
                    self.format_message(msg),
                    "-" * 60,
                    "",
                ]
            )
        return "\n".join(output)
