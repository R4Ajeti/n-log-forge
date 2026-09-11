"""Producer-side immutable event snapshots, without retaining traceback frames."""

from __future__ import annotations

import logging
import math
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType, TracebackType
from typing import Any

from ..constant.event_constant import (
    EXCEPTION_FRAMES_KEY_STR,
    EXCEPTION_MAX_CHAIN_LENGTH_INT,
    EXCEPTION_MAX_FRAMES_INT,
    EXCEPTION_MAX_TEXT_LENGTH_INT,
    EXCEPTION_MODULE_KEY_STR,
    EXCEPTION_STACKTRACE_KEY_STR,
    EXCEPTION_TYPE_KEY_STR,
    EXCEPTION_VALUE_KEY_STR,
    EXCEPTION_VALUES_KEY_STR,
    FRAME_FILENAME_KEY_STR,
    FRAME_FUNCTION_KEY_STR,
    FRAME_LINENO_KEY_STR,
    INTERNAL_PREFIX_STR,
    METADATA_CYCLE_STR,
    METADATA_INTEGER_TOO_LARGE_STR,
    METADATA_MAX_DEPTH_INT,
    METADATA_MAX_DEPTH_STR,
    METADATA_MAX_INTEGER_BITS_INT,
    METADATA_MAX_ITEMS_INT,
    METADATA_MAX_NODES_INT,
    METADATA_MAX_STRING_LENGTH_INT,
    METADATA_NONFINITE_STR,
    METADATA_TRUNCATED_KEY_SUFFIX_FORMAT_STR,
    METADATA_TRUNCATED_STR,
    METADATA_TRUNCATION_KEY_STR,
    METADATA_UNAVAILABLE_STR,
    METADATA_UNSUPPORTED_STR,
    RECORD_ASCTIME_KEY_STR,
    RECORD_MESSAGE_KEY_STR,
)
from .source import package_display_name
from .timing import capture_timing, format_duration

type FrozenValue = (
    None | bool | int | float | str | tuple["FrozenValue", ...] | Mapping[str, "FrozenValue"]
)

_STANDARD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    RECORD_MESSAGE_KEY_STR,
    RECORD_ASCTIME_KEY_STR,
}


def _bounded_text(text: str, limit: int = METADATA_MAX_STRING_LENGTH_INT) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(METADATA_TRUNCATED_STR))] + METADATA_TRUNCATED_STR


def _safe_representation(value: Any) -> str:
    try:
        representation = repr(value)
    except Exception:
        representation = METADATA_UNAVAILABLE_STR
    return _bounded_text(METADATA_UNSUPPORTED_STR.format(type(value).__name__, representation))


def _bounded_mapping_key(key: str, output: Mapping[str, FrozenValue]) -> str:
    candidate = _bounded_text(key)
    if candidate not in output:
        return candidate
    collision = 2
    while True:
        suffix = METADATA_TRUNCATED_KEY_SUFFIX_FORMAT_STR.format(collision)
        candidate = key[: METADATA_MAX_STRING_LENGTH_INT - len(suffix)] + suffix
        if candidate not in output:
            return candidate
        collision += 1


class _Snapshot:
    def __init__(self) -> None:
        self._ancestors: set[int] = set()
        self._remaining = METADATA_MAX_NODES_INT

    def convert(self, value: Any, depth: int = 0) -> FrozenValue:
        self._remaining -= 1
        if self._remaining < 0:
            return METADATA_TRUNCATED_STR
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value.bit_length() > METADATA_MAX_INTEGER_BITS_INT:
                return METADATA_INTEGER_TOO_LARGE_STR.format(value.bit_length())
            return value
        if isinstance(value, str):
            return _bounded_text(value)
        if isinstance(value, float):
            return value if math.isfinite(value) else METADATA_NONFINITE_STR.format(value)
        if not isinstance(value, (Mapping, list, tuple)):
            return _safe_representation(value)
        identity = id(value)
        if identity in self._ancestors:
            return METADATA_CYCLE_STR
        if depth >= METADATA_MAX_DEPTH_INT:
            return METADATA_MAX_DEPTH_STR
        self._ancestors.add(identity)
        try:
            if isinstance(value, Mapping):
                output: dict[str, FrozenValue] = {}
                for index, (key, item) in enumerate(value.items()):
                    if index >= METADATA_MAX_ITEMS_INT or self._remaining <= 0:
                        marker = METADATA_TRUNCATION_KEY_STR
                        while marker in output:
                            marker += "!"
                        output[marker] = METADATA_TRUNCATED_STR
                        break
                    if not isinstance(key, str):
                        return _safe_representation(value)
                    output[_bounded_mapping_key(key, output)] = self.convert(item, depth + 1)
                return MappingProxyType(output)
            sequence: list[FrozenValue] = []
            for index, item in enumerate(value):
                if index >= METADATA_MAX_ITEMS_INT or self._remaining <= 0:
                    sequence.append(METADATA_TRUNCATED_STR)
                    break
                sequence.append(self.convert(item, depth + 1))
            return tuple(sequence)
        except Exception:
            return _safe_representation(value)
        finally:
            self._ancestors.remove(identity)


def snapshot(value: Any) -> FrozenValue:
    """Copy JSON-compatible data into bounded immutable containers safely."""
    return _Snapshot().convert(value)


def thaw(value: FrozenValue) -> Any:
    """Materialize an independent JSON-compatible value for provider serialization."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def validate_metadata(
    extra: Mapping[str, Any] | None, metadata: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge facade metadata after rejecting collisions and reserved attributes."""
    if extra is not None and not isinstance(extra, Mapping):
        raise TypeError("extra must be a mapping with string keys")
    merged: dict[str, Any] = {}
    for collection in (extra or {}, metadata):
        for key, value in collection.items():
            if not isinstance(key, str):
                raise TypeError("Metadata keys must be strings")
            if key in _STANDARD_FIELDS or key.startswith(INTERNAL_PREFIX_STR):
                raise ValueError(f"Metadata key {key!r} is reserved")
            if key in merged:
                raise ValueError(f"Duplicate metadata key {key!r} in extra and keyword metadata")
            merged[key] = value
    return merged


@dataclass(frozen=True)
class Event:
    """An accepted record detached from mutable application and traceback objects."""

    timestamp: datetime
    level: int
    level_name: str
    source: str
    package_name: str
    message: str
    metadata: Mapping[str, FrozenValue]
    pathname: str
    lineno: int
    function: str
    exception: Mapping[str, FrozenValue] | None
    exception_text: str | None
    stack_info: str | None
    operation: str | None
    elapsed_ns: int | None
    duration: str


def _exception_snapshot(
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None]
    | tuple[None, None, None]
    | None,
) -> tuple[Mapping[str, FrozenValue] | None, str | None]:
    if not exc_info or exc_info[1] is None:
        return None, None
    current: BaseException | None = exc_info[1]
    current_traceback = exc_info[2]
    values: list[FrozenValue] = []
    seen: set[int] = set()
    while (
        current is not None
        and id(current) not in seen
        and len(values) < EXCEPTION_MAX_CHAIN_LENGTH_INT
    ):
        seen.add(id(current))
        try:
            message = _bounded_text(str(current))
        except Exception:
            message = _safe_representation(current)
        frames: list[FrozenValue] = []
        frame_traceback = current_traceback
        while frame_traceback is not None and len(frames) < EXCEPTION_MAX_FRAMES_INT:
            code = frame_traceback.tb_frame.f_code
            frames.append(MappingProxyType({
                FRAME_FILENAME_KEY_STR: code.co_filename,
                FRAME_LINENO_KEY_STR: frame_traceback.tb_lineno,
                FRAME_FUNCTION_KEY_STR: code.co_name,
            }))
            frame_traceback = frame_traceback.tb_next
        value: dict[str, FrozenValue] = {
            EXCEPTION_TYPE_KEY_STR: type(current).__name__,
            EXCEPTION_VALUE_KEY_STR: message,
            EXCEPTION_MODULE_KEY_STR: type(current).__module__,
        }
        if frames:
            value[EXCEPTION_STACKTRACE_KEY_STR] = MappingProxyType({
                EXCEPTION_FRAMES_KEY_STR: tuple(frames)
            })
        values.append(MappingProxyType(value))
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
        current_traceback = current.__traceback__ if current is not None else None
    try:
        text = _bounded_text(
            "".join(traceback.format_exception(*exc_info)).rstrip(),
            EXCEPTION_MAX_TEXT_LENGTH_INT,
        )
    except Exception:
        text = "\n".join(
            f"{value[EXCEPTION_TYPE_KEY_STR]}: {value[EXCEPTION_VALUE_KEY_STR]}"
            for value in reversed(values)
            if isinstance(value, Mapping)
        )
    return MappingProxyType({EXCEPTION_VALUES_KEY_STR: tuple(reversed(values))}), text


def make_event(
    record: logging.LogRecord,
    package_name: str | None = None,
    duration_precision: int = 1,
) -> Event:
    """Enrich an accepted record in its producer context without mutating it."""
    operation, elapsed_ns = capture_timing()
    try:
        message = record.getMessage()
    except Exception:
        message = _safe_representation(record.msg)
    attributes = {
        key: value
        for key, value in record.__dict__.copy().items()
        if isinstance(key, str)
        and key not in _STANDARD_FIELDS
        and not key.startswith(INTERNAL_PREFIX_STR)
    }
    metadata_value = snapshot(attributes)
    metadata: Mapping[str, FrozenValue]
    if isinstance(metadata_value, Mapping):
        metadata = metadata_value
    else:
        metadata = MappingProxyType({METADATA_TRUNCATION_KEY_STR: metadata_value})
    exception, exception_text = _exception_snapshot(record.exc_info)
    if exception_text is None and record.exc_text:
        try:
            exception_text = _bounded_text(str(record.exc_text), EXCEPTION_MAX_TEXT_LENGTH_INT)
        except Exception:
            exception_text = _safe_representation(record.exc_text)
    return Event(
        timestamp=datetime.fromtimestamp(record.created, UTC),
        level=record.levelno,
        level_name=record.levelname,
        source=record.name,
        package_name=(
            package_name if package_name is not None else package_display_name(record.name)
        ),
        message=message,
        metadata=metadata,
        pathname=record.pathname,
        lineno=record.lineno,
        function=record.funcName or "<unknown>",
        exception=exception,
        exception_text=exception_text,
        stack_info=record.stack_info,
        operation=operation,
        elapsed_ns=elapsed_ns,
        duration=format_duration(elapsed_ns, duration_precision),
    )
