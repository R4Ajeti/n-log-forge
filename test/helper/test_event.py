import logging
import sys
from collections.abc import Mapping
from types import TracebackType

import pytest

from core.constant.event_constant import (
    METADATA_MAX_ITEMS_INT,
    METADATA_MAX_STRING_LENGTH_INT,
)
from core.helper import timing
from core.helper.event import make_event, snapshot, thaw, validate_metadata


def record(message="Message", args=(), exc_info=None, **metadata):
    value = logging.LogRecord("my_package.api", 35, "/app/service.py", 42, message, args, exc_info)
    value.__dict__.update(metadata)
    return value


def test_event_materializes_without_mutating_record_and_freezes_metadata():
    mutable = {"items": [1, {"active": True}]}
    value = record("Processed %s", (12,), payload=mutable)
    original = value.__dict__.copy()
    event = make_event(value, package_name="Explicit Name")
    mutable["items"].append(99)
    mutable["items"][1]["active"] = False
    assert event.message == "Processed 12"
    assert event.source == "my_package.api"
    assert event.package_name == "Explicit Name"
    assert event.level == 35
    assert event.level_name == "Level 35"
    assert event.pathname == "/app/service.py"
    assert event.lineno == 42
    assert event.duration == "-"
    assert thaw(event.metadata) == {"payload": {"items": [1, {"active": True}]}}
    assert value.__dict__ == original
    assert "message" not in value.__dict__
    with pytest.raises(TypeError):
        event.metadata["payload"] = "changed"
    with pytest.raises(TypeError):
        event.metadata["payload"]["items"][1]["active"] = False


def test_timing_is_captured_before_message_interpolation(monkeypatch):
    clock = [100]
    monkeypatch.setattr(timing, "perf_counter_ns", lambda: clock[0])

    class Message:
        def __str__(self):
            clock[0] = 10_000_000_000
            return "late"

    with timing.timed("operation"):
        clock[0] = 200
        event = make_event(record(Message()))
    assert event.elapsed_ns == 100
    assert event.duration == "0.1s"
    assert event.operation == "operation"


def test_bounded_cycle_broken_repr_nonfinite_and_unsupported_metadata():
    class Broken:
        def __repr__(self):
            raise RuntimeError("broken repr")

        def __str__(self):
            raise RuntimeError("broken str")

    cycle = []
    cycle.append(cycle)
    converted = thaw(snapshot({
        "cycle": cycle,
        "broken": Broken(),
        "nan": float("nan"),
        "infinity": float("inf"),
        "long": "a" * (METADATA_MAX_STRING_LENGTH_INT + 1),
        "many": list(range(METADATA_MAX_ITEMS_INT + 1)),
        "nonstring": {1: "value"},
    }))
    assert converted["cycle"] == ["<cycle>"]
    assert "<unavailable>" in converted["broken"]
    assert converted["nan"] == "<non-finite: nan>"
    assert converted["infinity"] == "<non-finite: inf>"
    assert len(converted["long"]) == METADATA_MAX_STRING_LENGTH_INT
    assert converted["long"].endswith("<truncated>")
    assert len(converted["many"]) == METADATA_MAX_ITEMS_INT + 1
    assert converted["many"][-1] == "<truncated>"
    assert converted["nonstring"].startswith("<dict:")


def test_huge_integer_uses_visible_bounded_fallback():
    converted = thaw(snapshot({"huge": 1 << 5000}))
    assert converted == {"huge": "<integer-too-large: 5001 bits>"}


def test_truncated_mapping_keys_remain_distinct_and_bounded():
    prefix = "k" * METADATA_MAX_STRING_LENGTH_INT
    converted = thaw(snapshot({prefix + "a": 1, prefix + "b": 2}))
    assert list(converted.values()) == [1, 2]
    assert len(converted) == 2
    assert all(len(key) <= METADATA_MAX_STRING_LENGTH_INT for key in converted)
    assert any(key.endswith("<truncated:2>") for key in converted)


def test_depth_and_total_node_budgets_are_visible():
    deep = []
    current = deep
    for _ in range(20):
        child = []
        current.append(child)
        current = child
    assert "<max-depth>" in repr(thaw(snapshot(deep)))
    wide = [[list(range(100)) for _ in range(100)] for _ in range(100)]
    assert "<truncated>" in repr(thaw(snapshot(wide)))


@pytest.mark.parametrize("key", ["msg", "message", "asctime", "name", "levelno", "nlf_private"])
def test_metadata_collision_validation(key):
    with pytest.raises(ValueError, match="reserved"):
        validate_metadata({key: 1}, {})
    with pytest.raises(ValueError, match="reserved"):
        validate_metadata(None, {key: 1})


def test_metadata_merge_duplicate_and_key_type_validation():
    assert validate_metadata({"left": 1}, {"right": 2}) == {"left": 1, "right": 2}
    with pytest.raises(ValueError, match="Duplicate"):
        validate_metadata({"same": 1}, {"same": 2})
    with pytest.raises(TypeError, match="strings"):
        validate_metadata({1: "bad"}, {})
    with pytest.raises(TypeError, match="mapping"):
        validate_metadata([], {})


def test_exception_chain_structured_stack_and_no_traceback_references():
    try:
        try:
            raise ValueError("root cause")
        except ValueError as error:
            raise RuntimeError("outer failure") from error
    except RuntimeError:
        value = record("Failed", exc_info=sys.exc_info())
    value.stack_info = "Stack independently requested"
    event = make_event(value)
    assert event.stack_info == "Stack independently requested"
    exceptions = thaw(event.exception)["values"]
    assert [item["type"] for item in exceptions] == ["ValueError", "RuntimeError"]
    assert exceptions[-1]["value"] == "outer failure"
    assert exceptions[-1]["stacktrace"]["frames"][-1]["function"] == (
        "test_exception_chain_structured_stack_and_no_traceback_references"
    )
    assert "direct cause" in event.exception_text

    def assert_detached(item):
        assert not isinstance(item, (TracebackType, BaseException))
        if isinstance(item, Mapping):
            for child in item.values():
                assert_detached(child)
        elif isinstance(item, tuple):
            for child in item:
                assert_detached(child)

    assert_detached(event.exception)
    assert make_event(record(exc_info=(None, None, None))).exception is None


def test_bad_message_and_exception_str_do_not_suppress_event():
    class BrokenError(Exception):
        def __str__(self):
            raise RuntimeError("str failure")

        def __repr__(self):
            raise RuntimeError("repr failure")

    try:
        raise BrokenError()
    except BrokenError:
        value = record(BrokenError(), exc_info=sys.exc_info())
    event = make_event(value)
    assert "<unavailable>" in event.message
    assert event.exception_text
    assert "BrokenError" in event.exception_text


def test_broken_existing_exception_text_is_safely_snapshotted():
    class BrokenText:
        def __str__(self):
            raise RuntimeError("broken string")

        def __repr__(self):
            raise RuntimeError("broken representation")

    value = record()
    value.exc_text = BrokenText()
    assert make_event(value).exception_text == "<BrokenText: <unavailable>>"
