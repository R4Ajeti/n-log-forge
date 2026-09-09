import asyncio
import contextvars
import threading

import pytest

from core.helper import timing


@pytest.fixture
def clock(monkeypatch):
    current = [0]
    monkeypatch.setattr(timing, "perf_counter_ns", lambda: current[0])
    return current


@pytest.mark.parametrize(
    ("nanoseconds", "expected"),
    [
        (0, "0.0s"),
        (1_000_000, "0.1s"),
        (99_000_000, "0.1s"),
        (100_000_000, "0.1s"),
        (101_000_000, "0.2s"),
        (842_000_000, "0.9s"),
        (1_000_000_000, "1.0s"),
        (1_001_000_000, "1.1s"),
        (1_210_000_000, "1.3s"),
        (2_000_000_000, "2.0s"),
        (12_310_000_000, "12.4s"),
    ],
)
def test_required_ceiling_boundaries(nanoseconds, expected):
    assert timing.format_duration(nanoseconds) == expected


@pytest.mark.parametrize("precision", range(7))
def test_precisions_are_exact_integer_ceiling(precision):
    quantum = 10 ** (9 - precision)
    value = timing.format_duration(quantum + 1, precision)
    expected = "2s" if precision == 0 else "0." + "0" * (precision - 1) + "2s"
    assert value == expected
    assert timing.format_duration(None, precision) == "-"


def test_nested_restore_and_explicit_stop_are_idempotent(clock):
    assert timing.capture_timing() == (None, None)
    outer = timing.start_timer("outer")
    clock[0] = 50
    inner = timing.start_timer("inner")
    clock[0] = 100
    assert timing.capture_timing() == ("inner", 50)
    with pytest.raises(RuntimeError, match="nesting order"):
        outer.stop()
    assert timing.capture_timing() == ("inner", 50)
    assert inner.stop() == 50 / 1e9
    clock[0] = 150
    assert inner.elapsedSeconds == inner.stop() == 50 / 1e9
    assert timing.capture_timing() == ("outer", 150)
    outer.stop()
    assert timing.capture_timing() == (None, None)
    with pytest.raises(AttributeError):
        inner.elapsedSeconds = 10


def test_copied_context_must_not_stop_parent_and_retains_immutable_entry(clock):
    timer = timing.start_timer("parent")
    copied = contextvars.copy_context()
    with pytest.raises(RuntimeError, match="starting context"):
        copied.run(timer.stop)
    clock[0] = 100
    timer.stop()
    clock[0] = 200
    assert copied.run(timing.capture_timing) == ("parent", 200)
    assert timing.capture_timing() == (None, None)
    assert timer.elapsedSeconds == 100 / 1e9


def test_context_manager_restores_after_error_and_reentrant_scope(clock):
    scope = timing.timed("work")
    with scope as outer:
        clock[0] = 100
        with pytest.raises(LookupError), scope as inner:
            clock[0] = 150
            raise LookupError("application error")
        assert inner.elapsedSeconds == 50 / 1e9
        assert timing.capture_timing() == ("work", 150)
    assert outer.elapsedSeconds == 150 / 1e9
    assert timing.capture_timing() == (None, None)


def test_recursive_decorator_preserves_return_metadata_and_parent(clock):
    observed = []

    @timing.timed("recursive")
    def recurse(depth):
        """Useful function documentation."""
        clock[0] += 100
        if depth:
            result = recurse(depth - 1)
            observed.append(timing.capture_timing())
            return result + 1
        return 0

    assert recurse(2) == 2
    assert recurse.__name__ == "recurse"
    assert recurse.__doc__ == "Useful function documentation."
    assert observed == [("recursive", 200), ("recursive", 300)]
    assert timing.capture_timing() == (None, None)


def test_async_decorator_times_awaited_body_and_concurrent_reuse(clock):
    async def scenario():
        started = [asyncio.Event(), asyncio.Event()]
        release = asyncio.Event()

        @timing.timed("async-work")
        async def work(index):
            started[index].set()
            await release.wait()
            return timing.capture_timing()

        first_coroutine = work(0)
        assert timing.capture_timing() == (None, None)
        first = asyncio.create_task(first_coroutine)
        await started[0].wait()
        clock[0] = 100
        second = asyncio.create_task(work(1))
        await started[1].wait()
        clock[0] = 300
        release.set()
        assert await first == ("async-work", 300)
        assert await second == ("async-work", 200)
        assert timing.capture_timing() == (None, None)

    asyncio.run(scenario())


def test_cancellation_restores_child_context(clock):
    async def scenario():
        started = asyncio.Event()
        captured = []

        async def work():
            try:
                with timing.timed("cancelled"):
                    started.set()
                    await asyncio.Future()
            finally:
                captured.append(timing.capture_timing())

        task = asyncio.create_task(work())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert captured == [(None, None)]

    asyncio.run(scenario())


def test_ordinary_threads_isolate_but_to_thread_inherits(clock):
    thread_values = []
    with timing.timed("parent"):
        thread = threading.Thread(target=lambda: thread_values.append(timing.capture_timing()))
        thread.start()
        thread.join()
        assert thread_values == [(None, None)]
        assert asyncio.run(asyncio.to_thread(timing.capture_timing)) == ("parent", 0)


def test_generator_decorators_and_empty_operations_are_rejected():
    def generator():
        yield 1

    async def async_generator():
        yield 1

    for function in (generator, async_generator):
        with pytest.raises(TypeError, match="generator"):
            timing.timed("work")(function)
    for name in ("", "   ", None, 3):
        with pytest.raises(ValueError, match="non-empty"):
            timing.timed(name)
