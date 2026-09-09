"""Typed user-facing logger without replacing standard-library logging objects."""

from __future__ import annotations

import logging
import threading
from typing import Any

from ..helper.event import validate_metadata
from ..helper.normalization import normalize_logger_name
from ..helper.source import resolve_caller
from ..helper.timing import TimerHandle, Timed, start_timer, timed
from . import runtime


def _severity(level: int) -> int:
    if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 50:
        raise ValueError("record level must be a positive integer severity from 1 through 50")
    return level


class Logger:
    """Reusable facade whose calls observe current process-wide configuration.

    Positional arguments use lazy standard ``%`` interpolation. ``exc_info``,
    ``stack_info``, ``stacklevel`` and ``extra`` are standard logging controls;
    other keywords are structured metadata. This is not a logging.Logger.
    """

    def __init__(self, name: str | None) -> None:
        self._name = name

    @property
    def name(self) -> str | None:
        """Explicit name, or None for the caller-resolving convenience logger."""
        return self._name

    def isEnabledFor(self, level: int) -> bool:
        """Report owned threshold and standard creation-gate eligibility."""
        level = _severity(level)
        name = self._name or resolve_caller().source
        return runtime.RUNTIME.enabled(name, level)

    def _emit(
        self,
        level: int,
        msg: object,
        args: tuple[object, ...],
        *,
        exc_info: Any = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Any = None,
        **metadata: object,
    ) -> None:
        if isinstance(stacklevel, bool) or not isinstance(stacklevel, int) or stacklevel < 1:
            raise ValueError("stacklevel must be a positive integer")
        merged = validate_metadata(extra, metadata)
        # Named calls avoid caller inspection until both severity gates pass.
        # Global calls must resolve first because a package may allow DEBUG.
        name = self._name or resolve_caller(stacklevel).source
        if not runtime.RUNTIME.enabled(name, level):
            return
        logging.getLogger(name).log(
            level, msg, *args, exc_info=exc_info, stack_info=stack_info,
            stacklevel=stacklevel + 2, extra=merged,
        )

    def debug(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Emit DEBUG with lazy formatting and structured keyword metadata."""
        self._emit(logging.DEBUG, msg, args, **kwargs)

    def info(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Emit INFO with lazy formatting and structured keyword metadata."""
        self._emit(logging.INFO, msg, args, **kwargs)

    def warning(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Emit WARNING with lazy formatting and structured keyword metadata."""
        self._emit(logging.WARNING, msg, args, **kwargs)

    def error(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Emit ERROR; use exc_info=True to include a current exception."""
        self._emit(logging.ERROR, msg, args, **kwargs)

    def critical(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Emit CRITICAL with lazy formatting and structured keyword metadata."""
        self._emit(logging.CRITICAL, msg, args, **kwargs)

    def exception(self, msg: object, *args: object, exc_info: Any = True, **kwargs: Any) -> None:
        """Emit ERROR with current exception information unless overridden."""
        self._emit(logging.ERROR, msg, args, exc_info=exc_info, **kwargs)

    def log(self, level: int, msg: object, *args: object, **kwargs: Any) -> None:
        """Emit a numeric severity in 1..50, including nonstandard severities."""
        self._emit(_severity(level), msg, args, **kwargs)

    def timed(self, name: str) -> Timed:
        """Create a context manager or synchronous/async function decorator."""
        return timed(name)

    def startTimer(self, name: str) -> TimerHandle:
        """Start an operation; stop the handle in this context and nesting order."""
        return start_timer(name)


_FACADES: dict[str, Logger] = {}
_FACADE_LOCK = threading.Lock()
logger = Logger(None)


def getLogger(name: str) -> Logger:
    """Return a cached named facade without configuring Python logging."""
    normalized = normalize_logger_name(name, package_rule=False)
    with _FACADE_LOCK:
        if normalized not in _FACADES:
            _FACADES[normalized] = Logger(normalized)
        return _FACADES[normalized]
