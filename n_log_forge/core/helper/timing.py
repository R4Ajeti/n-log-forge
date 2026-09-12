"""Private context-local operations with immutable inherited stack entries."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from functools import wraps
from time import perf_counter_ns
from types import TracebackType
from typing import Any, TypeVar, cast

from ..constant.event_constant import (
    MAX_DURATION_PRECISION_INT,
    MISSING_DURATION_STR,
    NANOSECONDS_PER_SECOND_INT,
)

_Function = TypeVar("_Function", bound=Callable[..., Any])


@dataclass(frozen=True)
class _Entry:
    name: str
    start_ns: int


_stack: ContextVar[tuple[_Entry, ...]] = ContextVar("n_log_forge_timing", default=())


def _operation_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Operation name must be a non-empty string")
    return name.strip()


class TimerHandle:
    """An operation handle; stop it in its starting context and nesting order."""

    __slots__ = ("_entry", "_token", "_elapsed_ns")

    def __init__(self, name: str) -> None:
        self._entry = _Entry(_operation_name(name), perf_counter_ns())
        self._token: Token[tuple[_Entry, ...]] = _stack.set((*_stack.get(), self._entry))
        self._elapsed_ns: int | None = None

    @property
    def elapsedSeconds(self) -> float:
        """Elapsed seconds, frozen at the first successful stop."""
        elapsed = self._elapsed_ns
        if elapsed is None:
            elapsed = max(0, perf_counter_ns() - self._entry.start_ns)
        return elapsed / NANOSECONDS_PER_SECOND_INT

    def stop(self) -> float:
        """Restore the previous operation and return elapsed seconds, idempotently."""
        if self._elapsed_ns is not None:
            return self._elapsed_ns / NANOSECONDS_PER_SECOND_INT
        current = _stack.get()
        if not current or current[-1] is not self._entry:
            raise RuntimeError("Timer must be stopped in its starting context and nesting order")
        elapsed = max(0, perf_counter_ns() - self._entry.start_ns)
        try:
            _stack.reset(self._token)
        except ValueError:
            raise RuntimeError("Timer must be stopped in its starting context") from None
        self._elapsed_ns = elapsed
        return elapsed / NANOSECONDS_PER_SECOND_INT


class Timed:
    """Reusable synchronous context manager and sync/async function decorator."""

    def __init__(self, name: str) -> None:
        self._name = _operation_name(name)
        self._handles: ContextVar[tuple[TimerHandle, ...]] = ContextVar(
            "n_log_forge_scope_handles", default=()
        )

    def __enter__(self) -> TimerHandle:
        handle = start_timer(self._name)
        self._handles.set((*self._handles.get(), handle))
        return handle

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        handles = self._handles.get()
        if not handles:
            raise RuntimeError("Timing context exit has no matching entry")
        handles[-1].stop()
        self._handles.set(handles[:-1])

    def __call__(self, function: _Function) -> _Function:
        if inspect.isgeneratorfunction(function) or inspect.isasyncgenfunction(function):
            raise TypeError(
                "Timing decorators do not support generator or async-generator functions"
            )
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                with self:
                    return await function(*args, **kwargs)

            return cast(_Function, async_wrapped)

        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with self:
                return function(*args, **kwargs)

        return cast(_Function, wrapped)


def timed(name: str) -> Timed:
    """Create a reusable timer context/decorator without starting an operation."""
    return Timed(name)


def start_timer(name: str) -> TimerHandle:
    """Immediately begin a timing operation in the current context."""
    return TimerHandle(name)


def capture_timing() -> tuple[str | None, int | None]:
    """Snapshot the innermost operation using the producer's monotonic clock."""
    stack = _stack.get()
    if not stack:
        return None, None
    entry = stack[-1]
    return entry.name, max(0, perf_counter_ns() - entry.start_ns)


def format_duration(elapsed_ns: int | None, precision: int = 1) -> str:
    """Ceiling-round integer nanoseconds without binary floating point rounding."""
    if isinstance(precision, bool) or not isinstance(precision, int) or not (
        0 <= precision <= MAX_DURATION_PRECISION_INT
    ):
        raise ValueError("Duration precision must be an integer from 0 through 6")
    if elapsed_ns is None:
        return MISSING_DURATION_STR
    quantum_ns = 10 ** (9 - precision)
    units = (max(0, elapsed_ns) + quantum_ns - 1) // quantum_ns
    if precision == 0:
        return f"{units}s"
    whole, fractional = divmod(units, 10**precision)
    return f"{whole}.{fractional:0{precision}d}s"
