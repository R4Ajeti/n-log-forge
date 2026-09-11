# Finalize Console Rendering, Event Snapshots, Source Detection, and Timing

Parent specification: [`000001_build_reusable_structured_logging_package_with_sentry_support.md`](000001_build_reusable_structured_logging_package_with_sentry_support.md)

## Outcome and scope

Verify and maintain the already implemented producer-side event snapshot, deterministic
console provider, caller/source detection, package display names, structured metadata,
exception capture, and timing APIs. Fix regressions without making providers parse
rendered console text or retaining mutable application objects.

This plan covers parent sections 7 through 9 and their formatting/source,
metadata/exceptions, timing, and relevant performance acceptance cases from section 13.

## Implemented baseline

- Accepted `LogRecord` instances become frozen `Event` values before provider delivery.
- Mutable metadata is copied into bounded immutable tuples/mappings; cycles, excessive
  depth/items/nodes/string length, non-finite floats, huge integers, unsupported values,
  and failing `repr`/`str` paths receive visible safe fallbacks.
- Truncated mapping keys stay bounded and distinct rather than silently overwriting one
  another.
- Exception chains, bounded frame data, traceback text, and independent stack info are
  captured without retaining traceback/frame/application-object references.
- Console output uses UTC milliseconds by default, writes to current `stderr`, preserves
  caller-owned streams, applies fixed minimum widths, and expands long values.
- Header values, metadata keys, JSON values, delimiters, terminal controls, line
  separators, and unpaired Unicode surrogates are rendered safely and deterministically.
- Caller resolution skips facade/internal frames, honors `stacklevel`, handles global
  and named facades, and supplies stable `__main__` fallbacks and display names.
- `timed`, `startTimer`, and the handle contract use context-local immutable stacks and
  `perf_counter_ns()` with integer ceiling rounding for precision `0..6`.
- Sync/async decorators, nesting, recursion, cancellation, copied task/thread contexts,
  explicit stop ordering, and producer-context capture have deterministic tests.

## Requirement coverage

| Area | Required behavior | Primary implementation/tests |
| --- | --- | --- |
| Event snapshot | Immutable bounded structured fields produced after severity acceptance | `core/helper/event.py`, `test/helper/test_event.py` |
| Console | Exact columns, UTC/custom timestamps, JSON metadata, escaping, stream ownership | `core/proxy/console.py`, `test/proxy/test_console.py` |
| Source/display | Correct caller, `stacklevel`, global caller, `__main__`, display override | `core/helper/source.py`, `test/helper/test_source.py` |
| Metadata | Controls separated from metadata, collision rules, copy/fallback limits | `core/service/facade.py`, `core/helper/event.py`, related tests |
| Exceptions | Type/message/chain/frames/text/stack captured independently and safely | `core/helper/event.py`, `test/helper/test_event.py` |
| Timing | Three API forms, exact ceiling rounding, context isolation/inheritance | `core/helper/timing.py`, `test/helper/test_timing.py`, `test/service/test_facade.py` |

## Verification plan

1. Compare the empty-metadata console line byte-for-byte with the parent format,
   including UTC milliseconds, separators, minimum widths, `-` duration, and newline.
2. Test custom timestamp formats, long columns, deterministic metadata ordering, compact
   nested JSON, quoted ambiguous keys, multiline exception/stack text, terminal control
   characters, literal pipes, and malformed Unicode.
3. Confirm custom third-party record attributes are extracted from a copy and foreign
   records remain unchanged.
4. Exercise every snapshot limit plus collisions between overlong keys. Confirm values
   are immutable and independent from mutations made after the logging call.
5. Exercise broken interpolation, exception stringification, preformatted exception
   text, chained exceptions, explicit `exc_info`, and independent `stack_info` while
   retaining a valid console event.
6. Verify global/named caller attribution, nested wrappers with `stacklevel`, source
   versus display override, hyphen/underscore display handling, and `__main__` fallbacks.
7. Exercise every duration boundary in the parent table for precision `0..6` using a
   controlled nanosecond clock; do not use timing sleeps.
8. Verify context manager, sync decorator, async decorator, explicit handle, repeat stop,
   misuse recovery, recursion, concurrent reuse, exceptions, cancellation, task copies,
   `asyncio.to_thread()`, and ordinary-thread isolation.
9. Confirm rejected severity paths avoid interpolation, caller work where possible,
   traceback formatting, snapshot conversion, and provider serialization.

## Acceptance criteria

- Console output is deterministic, unambiguous, single-record safe, and cannot be
  suppressed by ordinary conversion or encoding failures.
- Streams remain application-owned and current `sys.stderr` is resolved at emission.
- Events contain every required field and no live mutable metadata, traceback frame,
  exception object, or producer timing lookup survives into provider consumption.
- Metadata bounds and fallback markers are visible, stable, and cannot silently discard
  a distinct key through truncation collision.
- Caller/source/display behavior matches the public API for direct, wrapped, global,
  named, and `__main__` calls.
- Timing output uses the specified integer ceiling algorithm and context state remains
  isolated while honoring intentional Python context copying.
- Exceptions and cancellation propagate from user code; timing cleanup restores the
  prior context in `finally`.

## Commands

```bash
python -m pytest -q \
  test/helper/test_event.py \
  test/helper/test_source.py \
  test/helper/test_timing.py \
  test/proxy/test_console.py \
  test/service/test_facade.py
python -m ruff check core test
python -m mypy
```

Report any gap against the parent specification explicitly. Keep rendering concerns in
the console provider and structured-data concerns in the immutable event boundary.
