import io
import logging
from dataclasses import replace
from datetime import UTC, datetime

from core.helper.event import make_event
from core.proxy.console import ConsoleProvider


def event(**metadata):
    record = logging.LogRecord(
        "my_package.api", logging.INFO, "api.py", 12, "Application started", (), None
    )
    record.created = datetime(2026, 9, 9, 20, 35, 42, 182123, tzinfo=UTC).timestamp()
    record.__dict__.update(metadata)
    return make_event(record)


def test_console_required_columns_utc_milliseconds_and_no_empty_separator():
    output = ConsoleProvider().format(event())
    assert output == (
        "2026-09-09 20:35:42.182Z | INFO     | My Package      |     - | "
        "my_package.api      | Application started"
    )
    assert len(output.split(" | ")) == 6


def test_custom_utc_format_preserves_microseconds():
    assert ConsoleProvider("%Y/%m/%d %H:%M:%S.%f %z").format(event()).startswith(
        "2026/09/09 20:35:42.182123 +0000 | "
    )


def test_metadata_is_sorted_compact_json_and_control_characters_are_escaped():
    output = ConsoleProvider().format(event(z="space | text\n\x1b", a={"z": 2, "a": True}))
    assert output.endswith(r' | a={"a":true,"z":2} z="space \u007c text\n\u001b"')
    assert "\x1b" not in output
    assert "\n" not in output


def test_metadata_keys_with_separators_are_json_quoted():
    output = ConsoleProvider().format(event(**{"a b": 1, "x=y": 2, "pipe|key": 3}))
    assert output.endswith(r' | "a b"=1 "pipe\u007ckey"=3 "x=y"=2')


def test_unpaired_surrogates_are_escaped_before_writing():
    broken = replace(event(), message="bad\ud800message")
    provider = ConsoleProvider(stream=io.StringIO())
    assert r"bad\ud800message" in provider.format(broken)
    provider.emit(broken)


def test_long_columns_expand_without_changing_following_record_widths():
    provider = ConsoleProvider()
    original = provider.format(event())
    record = logging.LogRecord(
        "long_source_name_without_truncation.api", 20, "", 0, "message", (), None
    )
    large = provider.format(make_event(record, "A package display name longer than its column"))
    assert record.name in large
    assert "A package display name longer than its column" in large
    assert provider.format(event()) == original


def test_console_writes_current_stderr_and_preserves_external_stream(monkeypatch):
    stream = io.StringIO()
    provider = ConsoleProvider()
    monkeypatch.setattr("sys.stderr", stream)
    provider.emit(event())
    assert stream.getvalue().endswith("Application started\n")
    assert provider.flush(0)
    assert provider.close(0)
    assert not stream.closed
