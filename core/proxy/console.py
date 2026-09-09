"""Standard-library console output; streams remain owned by the application."""

from __future__ import annotations

import json
import sys
import threading
from typing import TextIO

from ..constant.event_constant import (
    CONSOLE_DURATION_WIDTH_INT,
    CONSOLE_LEVEL_WIDTH_INT,
    CONSOLE_PACKAGE_WIDTH_INT,
    CONSOLE_SOURCE_WIDTH_INT,
    DEFAULT_TIMESTAMP_FORMAT_STR,
    TIMESTAMP_MILLISECOND_SUFFIX_STR,
)
from ..helper.event import Event, thaw


def escape_header(value: str) -> str:
    """Escape line breaks, backslashes, delimiters, and terminal control codes."""
    result: list[str] = []
    escapes = {"\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t", "|": "\\u007c"}
    for character in value:
        if character in escapes:
            result.append(escapes[character])
        elif ord(character) < 32 or 127 <= ord(character) <= 159:
            result.append(f"\\u{ord(character):04x}")
        elif character in ("\u2028", "\u2029"):
            result.append(f"\\u{ord(character):04x}")
        else:
            result.append(character)
    return "".join(result)


def _following_lines(value: str) -> str:
    return "\n".join(escape_header(line) for line in value.splitlines())


class ConsoleProvider:
    """Render accepted immutable events to stderr with fixed minimum widths.

    Text widths are level 8, package 15, and source 19; duration is right-aligned
    at width 5. No stream is closed. Lifecycle orchestration runs potentially
    blocking flush calls outside its caller's deadline-sensitive thread.
    """

    def __init__(
        self, timestamp_format: str | None = None, stream: TextIO | None = None
    ) -> None:
        self._timestamp_format = timestamp_format
        self._stream = stream
        self._lock = threading.RLock()

    def format(self, event: Event) -> str:
        if self._timestamp_format is None:
            timestamp = event.timestamp.strftime(DEFAULT_TIMESTAMP_FORMAT_STR)
            timestamp += TIMESTAMP_MILLISECOND_SUFFIX_STR.format(event.timestamp.microsecond // 1000)
        else:
            timestamp = event.timestamp.strftime(self._timestamp_format)
        line = (
            f"{escape_header(timestamp)} | "
            f"{escape_header(event.level_name):<{CONSOLE_LEVEL_WIDTH_INT}} | "
            f"{escape_header(event.package_name):<{CONSOLE_PACKAGE_WIDTH_INT}} | "
            f"{event.duration:>{CONSOLE_DURATION_WIDTH_INT}} | "
            f"{escape_header(event.source):<{CONSOLE_SOURCE_WIDTH_INT}} | "
            f"{escape_header(event.message)}"
        )
        if event.metadata:
            items = []
            for key in sorted(event.metadata):
                encoded = json.dumps(thaw(event.metadata[key]), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
                # JSON values already escape controls; escaping only literal pipes
                # preserves their compact JSON representation within the column.
                encoded = encoded.replace("|", r"\u007c")
                items.append(f"{escape_header(key)}={encoded}")
            line += " | " + " ".join(items)
        if event.exception_text:
            line += "\n" + _following_lines(event.exception_text)
        if event.stack_info:
            line += "\n" + _following_lines(event.stack_info)
        return line

    def emit(self, event: Event) -> None:
        output = self.format(event)
        with self._lock:
            stream = self._stream if self._stream is not None else sys.stderr
            stream.write(output + "\n")

    def flush(self, timeout: float = 2.0) -> bool:
        with self._lock:
            stream = self._stream if self._stream is not None else sys.stderr
            stream.flush()
        return True

    def close(self, timeout: float = 2.0) -> bool:
        return self.flush(timeout)
