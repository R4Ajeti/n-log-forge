# n-log-forge

`n-log-forge` is a typed structured-logging package for Python applications,
libraries, CLI tools, APIs, and workers. It uses standard-library
`logging.LogRecord` objects, writes predictable human-readable output to
`stderr`, carries operation timing across synchronous and AsyncIO code, and can
send explicitly owned events to Sentry without taking over a host Sentry client.

Python 3.14 or newer is required. The console provider has no runtime
dependencies. Sentry is optional.

## Quick start

Install the base package:

```shell
python -m pip install n-log-forge
```

Then log without a setup call:

```python
from n_log_forge import logger

logger.info("Application started")
logger.warning("Database response was slow")
logger.error("Authentication failed")
```

The first facade call initializes the owned pipeline and writes the default
console format to `stderr`:

```text
2026-09-09 20:35:42.182Z | INFO     | My Package      |     - | my_package.api      | Application started
```

The timestamp and caller shown above are illustrative.

For applications, calling `configure()` at startup is recommended. It validates
configuration eagerly and lets the package capture ordinary third-party records
before the first facade call.

## Public API

The supported top-level API is:

```python
from n_log_forge import (
    configure,
    flush,
    getLogger,
    logger,
    resetPackageLevel,
    setPackageLevel,
    shutdown,
)
```

`logger` and values returned by `getLogger()` are typed facades over standard
logging; they are not `logging.Logger` instances. Existing facades always see
later configuration changes. `getLogger(name)` requires a non-empty,
case-sensitive dotted name and reuses the facade for that exact name.

```python
from n_log_forge import getLogger

log = getLogger(__name__)
log.info(
    "Processed %s items",
    12,
    requestId="abc123",
    statusCode=200,
)
```

The facade supports `debug`, `info`, `warning`, `error`, `critical`,
`exception`, `log`, and `isEnabledFor`. `warn` remains a compatibility alias;
new code should use `warning`. Positional arguments retain lazy `%` formatting.
The standard `exc_info`, `stack_info`, `stacklevel`, and `extra` controls are
preserved; other keyword arguments are structured metadata.

### Exceptions

```python
try:
    perform_operation()
except Exception:
    log.exception("Operation failed", requestId="abc123")
```

Exception type, message, chain, traceback, caller information, timing, and
metadata are snapshotted before remote dispatch. `exc_info` and `stack_info`
remain independent controls.

### Standard logging interoperability

Once initialized, the owned root dispatch handler can receive ordinary records:

```python
import logging

logging.getLogger("dependency.client").error("Dependency failed")
```

Incoming records keep their `LogRecord.name`, numeric/name severity, caller,
exception, stack information, and custom attributes. The package copies them;
it does not mutate records observed by foreign handlers. Third-party callers use
the standard `extra={...}` mechanism rather than facade keyword metadata.

Records emitted before initialization remain entirely under the host's existing
logging configuration.

## Timing operations

Each console record has a duration column. It contains `-` outside an active
operation and the elapsed time from the innermost active operation otherwise.
Timing never emits records by itself.

Use a context manager:

```python
with log.timed("database_query") as timer:
    log.info("Fetching rows")

print(timer.elapsedSeconds)
```

Decorate synchronous or asynchronous functions:

```python
@log.timed("refresh_cache")
def refresh_cache():
    log.info("Refreshing")


@log.timed("fetch_user")
async def fetch_user():
    log.info("Fetching")
```

Or control an explicit handle:

```python
handle = log.startTimer("batch")
try:
    log.info("Processing batch")
finally:
    elapsed_seconds = handle.stop()
```

The same synchronous context manager works across `await` inside an async
function. Handles must be stopped in their starting context and in nesting
order. `stop()` is idempotent after a successful stop and freezes
`elapsedSeconds`. Generator and async-generator decorators are rejected because
timing their creation would be misleading.

The clock is monotonic and stored as integer nanoseconds. Display values are
ceiling-rounded. At the default precision of one decimal place, a positive
0.001-second operation displays as `0.1s`, 0.842 seconds as `0.9s`, and 1.210
seconds as `1.3s`. `durationPrecision` selects exactly `0..6` decimal places.

Timing state is context-local and immutable. Ordinary threads start clean;
AsyncIO child tasks and `asyncio.to_thread()` intentionally copy the current
context. A copied context can retain an inherited operation after its parent
exits. Start detached background tasks with a clean context when inheritance is
not wanted:

```python
import asyncio
import contextvars

task = asyncio.create_task(background_work(), context=contextvars.Context())
```

## Configuration

All `configure` options are keyword-only. Omitted options retain their existing
runtime overrides. A valid non-`None` value replaces one override; explicit
`None` removes only that override and reveals the environment or default value.
`configure()` with no arguments initializes without resetting anything.

| Programmatic option | Environment variable | Default or meaning |
| --- | --- | --- |
| `level` | `LOGGER` | Unconfigured; see the global decision table |
| `debugging` | `DEBUGGING` | Unconfigured; different from `False` |
| `consoleEnabled` | `CONSOLE_ENABLED` | `True` |
| `timestampFormat` | `TIMESTAMP_FORMAT` | UTC with milliseconds and `Z` |
| `packageName` | `PACKAGE_NAME` | Derived from the source name |
| `durationPrecision` | `DURATION_PRECISION` | `1`, range `0..6` |
| `sentryDataSourceName` | `SENTRY_DATA_SOURCE_NAME` | Absent; Sentry disabled |
| `sentryLevel` | `SENTRY_LEVEL` | `ERROR` |
| `sentryEnvironment` | `SENTRY_ENVIRONMENT` | Owned client uses `production` |
| `sentryRelease` | `SENTRY_RELEASE` | No inferred release |
| `manageRootLevel` | none | `True` |
| `rootHandlerPolicy` | none | `"preserve"` |
| `reloadEnvironment` | none | Per-call `False`; not stored |

Example incremental updates and resets:

```python
configure(level="info", consoleEnabled=True)
configure(packageName="My Service")       # retains earlier overrides
configure(packageName=None)               # environment/automatic name
configure(sentryDataSourceName="")        # masks an environment DSN
configure(sentryDataSourceName=None)      # reveals an environment DSN
configure(reloadEnvironment=True)         # replaces the environment snapshot
```

The environment is trimmed and read once at initialization. Missing, empty, and
whitespace-only values are absent. No `.env` file is loaded. A reload replaces
the complete environment snapshot, including variables removed since the prior
read, while retaining runtime overrides.

Every candidate source is validated before publication, including settings
shadowed by a higher-precedence source and Sentry settings while Sentry is
disabled. Resolution is runtime override, then environment, then default,
independently for each option and exact logger name. A failed initialization,
update, or reload preserves the active snapshot, handlers, gates, environment
snapshot, and provider clients; a later retry is allowed.

### Levels and booleans

Levels accept the following case-insensitive aliases or any integer threshold
from `0` through `50`. Trimmed ASCII decimal strings in that range also work.

| Numeric | Canonical | Aliases |
| ---: | --- | --- |
| 50 | `CRITICAL` | `critical`, `crit`, `c` |
| 40 | `ERROR` | `error`, `err`, `e` |
| 30 | `WARNING` | `warning`, `warn`, `w` |
| 20 | `INFO` | `info`, `i` |
| 10 | `DEBUG` | `debug`, `d` |
| 0 | `NOTSET` | `notset`, `none`, `n` |

Booleans accept actual booleans, integers `0`/`1`, and these trimmed,
case-insensitive strings:

- True: `true`, `1`, `yes`, `y`, `on`
- False: `false`, `0`, `no`, `n`, `off`

Other integers, booleans used as levels, floats, signed numeric strings, blank
direct parser inputs, and values outside their ranges are rejected. Facade
`log(level, ...)` emits only positive integer severities `1..50`; configuration
level zero means no additional global/provider restriction or explicit package
inheritance. Incoming third-party records retain custom severities, including
values above 50.

### Global level selection

`DEBUGGING=false` is not the same as leaving `DEBUGGING` absent:

| Effective `debugging` | Explicit level | Global threshold |
| --- | --- | --- |
| `True` | missing or present | `DEBUG` |
| `False` | present | configured level |
| `False` | missing | `ERROR` |
| unconfigured | present | configured level |
| unconfigured | missing | `INFO` |

For example, environment `DEBUGGING=true` plus `LOGGER=warning` remains `DEBUG`
even after `configure(level="info")`. Calling
`configure(debugging=False, level="info")` selects `INFO`.

### Per-logger rules

Use exact runtime rules to quiet or expand a dependency/package hierarchy:

```python
setPackageLevel("my_package", "debug")
setPackageLevel("requests", 30)
setPackageLevel("urllib3", "error")
resetPackageLevel("my_package")
```

The environment equivalent is:

```shell
export LOGGER=info
export LOGGER_PACKAGES="my_package=DEBUG,requests=warn,urllib3=40"
```

Names are trimmed but case-sensitive dotted paths. Matching uses whole path
segments: `foo` matches `foo.api`, never `foobar`. The most specific selected
nonzero rule wins after runtime-over-environment merging at each exact name. An
environment child can therefore outrank a runtime parent.

`setPackageLevel("my_package", 0)` stores an explicit inheritance directive. It
masks the environment rule at that exact name, then continues at the parent and
finally the global threshold. `resetPackageLevel("my_package")` removes only the
exact runtime entry, revealing its environment rule without removing children.

## Logging ownership and host controls

The package installs one identifiable dispatch handler on the root logger. With
the default `manageRootLevel=True`, it sets the root creation gate to `NOTSET`
and applies global/package thresholds inside its owned pipeline. An explicit
package rule sets that exact standard logger's gate to `1`, allowing a rule below
a restrictive unconfigured ancestor. These level changes can also change which
records reach foreign handlers, so they are process-wide even though foreign
handler objects are preserved.

Use `configure(manageRootLevel=False)` when the host must own the root level. A
restrictive host root/logger gate can then prevent records from being created
before the package sees them. The package never bypasses explicit levels on
unconfigured children, `logger.disabled`, `logging.disable()`, logger filters,
`propagate=False`, or descendant handlers. Adjust the relevant standard logger
when the host intentionally suppresses such records.

The package remembers gates it changes and restores them when the corresponding
rule disappears, root management is disabled, or shutdown occurs. A detectable
later host change is respected rather than overwritten.

`rootHandlerPolicy="preserve"` never removes, modifies, closes, or replaces
foreign handlers. Those handlers may produce additional output under their own
rules. The explicit `"replace"` policy detaches every existing root handler,
including file and network handlers, and restores them when leaving replacement
mode or shutting down. It leaves descendant handlers alone and does not
repeatedly detach handlers added later by the host.

Disabling the owned console is independent of Sentry:

```python
configure(consoleEnabled=False)
```

If console and Sentry are both disabled, the owned pipeline emits nothing;
foreign output remains under host control.

## Console records and metadata

Console records use:

```text
TIMESTAMP | LEVEL | PACKAGE | DURATION | SOURCE | MESSAGE [| METADATA]
```

Text columns have fixed minimum widths and expand without truncation. The
default timestamp is timezone-aware UTC with exactly three millisecond digits
and a literal `Z`. A custom `timestampFormat` is passed to `datetime.strftime`;
`%f` therefore produces six microsecond digits. Timestamp formatting does not
affect monotonic duration measurement.

Named facades use their explicit name as `SOURCE`; ordinary records use
`LogRecord.name`; the global facade resolves each caller independently. Under
`__main__`, it prefers `__spec__.name`, then the script filename stem, and never
uses an absolute path as the display source. The automatic package label comes
from the source's first segment, splitting underscores/hyphens and title-casing
the words. `packageName` overrides only this display label.

Header line breaks, delimiters, and terminal controls are escaped. Requested
tracebacks and stack information follow on readable escaped lines. Metadata is
sorted by key; values use compact JSON so strings and nested structures remain
unambiguous. The metadata separator is omitted when no metadata exists.

Facade metadata keys must be strings. Keys duplicated across `extra` and keyword
metadata, standard `LogRecord` fields (including `message` and `asctime`), and
the reserved `nlf_` prefix are rejected before dispatch. User values stay nested
inside provider metadata and cannot replace provider fields.

Metadata snapshots preserve JSON-compatible scalars, string-keyed mappings,
lists, and tuples within these bounds:

- maximum nesting depth: 6;
- maximum items per collection: 100, followed by a visible truncation marker;
- maximum string/key length: 4096 characters;
- maximum total visited nodes: 2000;
- maximum integer size: 4096 bits.

Cycles, oversized integers, non-finite floats, unsupported objects, and failed
representations become visible bounded fallback strings. Mutable values are
copied in the producer context before remote work. Metadata conversion and
remote-provider failures do not suppress otherwise valid console output or
escape an ordinary logging call.

The package always redacts its configured Sentry DSN from its representations
and diagnostics and never captures exception-frame locals by default. Callers
remain responsible for secrets they explicitly put in messages or metadata;
the package cannot make arbitrary application content secret-free.

## Sentry

Install the optional extra:

```shell
python -m pip install "n-log-forge[sentry]"
```

Sentry activates solely from the effective non-empty DSN:

```shell
export SENTRY_DATA_SOURCE_NAME="https://publicKey@example.ingest.sentry.io/123"
export SENTRY_ENVIRONMENT=production
export SENTRY_RELEASE=1.0.0
export SENTRY_LEVEL=error
```

Or configure it programmatically with a dummy/example DSN:

```python
configure(
    sentryDataSourceName="https://publicKey@example.ingest.sentry.io/123",
    sentryEnvironment="production",
    sentryRelease="1.0.0",
    sentryLevel="error",
)
```

Blank `configure(sentryDataSourceName="")` is the one allowed blank string: it
stores a disabled override and masks an environment DSN. Passing `None` removes
that override and may enable Sentry again. `SENTRY_ENABLED`, `SENTRY_DSN`, and
unrelated SDK environment settings cannot activate this provider. Malformed
configured DSNs fail local validation without network or SDK imports. A valid
effective DSN without the extra raises an error containing the exact install
command above.

Sentry receives a record only when it meets both its resolved logger threshold
and `sentryLevel`; providers never broaden logger eligibility. The default
Sentry threshold is `ERROR`, while level zero adds no provider restriction.
Custom numeric severities map deterministically: 50+ to `fatal`, 40+ to `error`,
30+ to `warning`, 20+ to `info`, and lower values to `debug`. The original
numeric/name severity remains in the structured event context.

The provider creates a private `sentry_sdk.Client`, disables default and
automatic integrations, and captures only explicit message/exception events.
It does not initialize, replace, enrich from, or close a host application's
global client. A separately configured host logging integration may also
capture the same standard record; the package guarantees only that its own path
attempts capture at most once.

No Sentry logs, breadcrumbs, unhandled-exception hooks, tracing, sessions,
profiles, metrics, frame locals, or source context are enabled. When not
configured, the SDK is not imported. With no configured environment, the owned
client explicitly uses `production`; with no release, it sends no inferred
release and does not inspect Git or the SDK's environment variables.

The SDK transport queue is bounded at 100 waiting envelopes and drops new work
when saturated. Runtime capture, serialization, and transport failures are
isolated from application logging and console delivery. Network work uses the
SDK transport worker; SDK-internal `sentry_sdk.*` records are never fed back to
the owned Sentry client. Synchronous console I/O may still block.

## Flush, shutdown, and processes

```python
if not flush(timeout=2.0):
    print("Some owned work did not finish within the budget")

shutdown(timeout=2.0)
```

Timeouts must be finite, nonnegative numbers and form one total budget across
providers. `flush` returns whether currently queued owned work drained without
known drops; it cannot prove durable remote delivery. `shutdown` stops intake,
detaches the owned handler, restores managed logging state, and attempts bounded
drain/cleanup. Both return `False` on failure or timeout.

Shutdown is idempotent. Busy resources are not closed beneath in-flight users,
and a later shutdown can complete timed-out cleanup. After shutdown, facade
records are dropped and `isEnabledFor()` is false until an explicit
`configure(...)` restarts the pipeline. Configuration values are retained;
package-rule helpers can update retained rules while stopped without restarting.
Timing APIs remain usable.

Call `flush`/`shutdown` explicitly in short-lived CLIs and workers. Delivery
cannot be guaranteed after crashes, forced termination, or network outages. A
normal interpreter exit also attempts bounded best-effort shutdown, but explicit
lifecycle calls make the result observable. Initialize each worker process after
it is created; reusing a live pre-fork SDK client or cross-process queue is
outside the supported contract.

## Development

The repository intentionally keeps its implementation in root-level `core/`,
with the stable import facade in root-level `n_log_forge/`. `core` is internal
and unsupported as a consumer API.

From the repository root, create a Python 3.14 environment and install all local
checks:

```shell
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev,sentry]"
```

Run the synchronous/AsyncIO example and verification commands:

```shell
python -m example.sync_async
python -m pytest
python -m ruff check .
python -m mypy
python -m build
```

Tests use controlled clocks, isolated logging state, and fake/owned transports;
they do not contact a live Sentry project. Build output is written to `dist/`.
CI runs the minimum supported Python version, builds both distribution formats,
and verifies that the base wheel imports and logs without Sentry installed.

## License

Licensed under the [MIT License](LICENSE).
