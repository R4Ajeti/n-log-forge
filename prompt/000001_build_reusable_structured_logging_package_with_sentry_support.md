# n-log-forge — Reusable Python Logging Package

Build a production-quality Python package distributed as `n-log-forge` and imported as `n_log_forge`. It must provide consistent structured logging for libraries, scripts, CLI tools, APIs, web applications, and workers, including synchronous, threaded, and AsyncIO code.

Implement the package, tests, packaging, and documentation described below. Keep the public API small, dependencies minimal, and configuration predictable. Each requirement has one authoritative definition; documentation and tests must follow those definitions.

## 1. Scope and deliverables

Deliver:

- A clean `src/n_log_forge/` package with a `pyproject.toml`, type hints, `py.typed`, and useful public API docstrings.
- A standard-library-based console implementation with no mandatory remote-provider SDK dependency.
- Sentry support through the optional extra `n-log-forge[sentry]`.
- Unit tests, focused integration tests, runnable examples, and a README covering the contracts below.
- Buildable wheel and source distributions, plus documented commands for installation, tests, linting, and type checking. Choose and declare a supported Python version range and verify its minimum version in CI.

Inspect existing repository instructions and files first. Preserve existing work and the repository's license. Do not publish releases, contact a live Sentry project during tests, or introduce application-specific behavior.

The first release includes console and Sentry providers. Keep an internal typed provider interface that can accommodate future providers without changing logging calls. A plugin discovery system, CLI/configuration-file adapters, additional remote providers, file rotation, a separate JSON console mode, tracing, and metrics are outside this release's scope.

## 2. Developer experience and public API

The simplest use must work without a setup call:

```python
from n_log_forge import logger

logger.info("Application started")
logger.warning("Database response was slow")
logger.error("Authentication failed")
```

Support named loggers, lazy message interpolation, and structured keyword metadata:

```python
from n_log_forge import getLogger

logger = getLogger(__name__)
logger.info("Processed %s items", 12, requestId="abc123", statusCode=200)
```

The required top-level API is:

```python
from n_log_forge import (
    logger,
    getLogger,
    configure,
    setPackageLevel,
    resetPackageLevel,
    flush,
    shutdown,
)
```

Preserve these public names and their camelCase configuration keywords. Internal names may follow ordinary Python conventions. Do not add redundant naming aliases. `warn()` may be a compatibility alias for `warning()`; document `warning()`.

The returned logger may be a typed facade over standard logging; it need not be an instance of `logging.Logger`. Document that distinction. It must support `debug`, `info`, `warning`, `error`, `critical`, `exception`, `log`, and `isEnabledFor`, plus the timing methods in section 8. `getLogger(name)` requires a non-empty name and returns a reusable facade for that name. Logger acquisition must not freeze configuration: existing facades see future updates.

Preserve standard `msg`, positional formatting arguments, `exc_info`, `stack_info`, `stacklevel`, and `extra` behavior. Additional keyword metadata is a feature of the facade; ordinary third-party `logging.Logger` calls continue to use `extra`.

`configure(...)` is the single entry point for global/provider configuration. The two package-level helpers update only their own runtime rule entries. `flush()` and `shutdown()` manage delivery and resources rather than configuration values.

### Initialization

- Import and logger acquisition must not install handlers, alter logging levels, initialize Sentry, perform network I/O, or raise errors for unused environment configuration.
- Initialize lazily on the first facade logging call or explicit configuration action. `isEnabledFor()` may initialize to resolve the effective configuration. Concurrent initialization must create only one owned pipeline.
- Explicit `configure()` with no arguments initializes eagerly. Recommend calling it at application startup to surface configuration errors and capture third-party records before the first facade call.
- Bare third-party logging calls before initialization are governed by the host's existing logging configuration.
- Read and normalize the supported environment variables once at initialization. Reload only through `configure(reloadEnvironment=True)`; never read the environment on every record.
- Initial configuration errors raise on the initializing call. Failed initialization must leave no partially installed pipeline and permit a later retry.
- Libraries should obtain loggers at module scope and leave application-wide configuration to the host. Document the process-wide effects of first use described in section 6.

## 3. Configuration contract

### Supported keys

All `configure` options are keyword-only. Omitted options retain their current runtime values. Defaults in this table are fallback values, not arguments implicitly supplied on every call.

| Programmatic key | Environment variable | Default / meaning |
| --- | --- | --- |
| `level` | `LOGGER` | Unconfigured; use the decision table in section 4 |
| `debugging` | `DEBUGGING` | Unconfigured; distinct from `False` |
| `consoleEnabled` | `CONSOLE_ENABLED` | `True` |
| `timestampFormat` | `TIMESTAMP_FORMAT` | UTC timestamp with milliseconds, as in section 7 |
| `packageName` | `PACKAGE_NAME` | Automatic display-name detection |
| `durationPrecision` | `DURATION_PRECISION` | Integer `1`; supported range `0..6` |
| `sentryDataSourceName` | `SENTRY_DATA_SOURCE_NAME` | No DSN; Sentry disabled |
| `sentryLevel` | `SENTRY_LEVEL` | `ERROR` |
| `sentryEnvironment` | `SENTRY_ENVIRONMENT` | Unspecified; document the selected SDK's fallback |
| `sentryRelease` | `SENTRY_RELEASE` | Unspecified; document the selected SDK's fallback |
| `manageRootLevel` | None | `True`; root creation-gate policy in section 6 |
| `rootHandlerPolicy` | None | `"preserve"`; opt-in `"replace"` in section 6 |
| `reloadEnvironment` | None | Per-call control, default `False`; not a stored override |

`LOGGER_PACKAGES` supplies the environment rule map in section 5. Use `setPackageLevel()` and `resetPackageLevel()` for its runtime counterparts; do not add a second competing rule-update API.

Reject unknown keyword arguments with a clear error. Do not add `SENTRY_ENABLED` or `sentryEnabled`. Unrecognized environment variables are ignored; in particular, `SENTRY_ENABLED` and the SDK's `SENTRY_DSN` must not activate this provider.

### Update, reset, and disable semantics

Use an internal omitted-value sentinel so omission and explicit `None` are distinguishable:

| Input to a stored configuration key | Effect |
| --- | --- |
| Omitted | Leave its runtime override unchanged |
| Valid non-`None` value | Replace its runtime override |
| Explicit `None` | Remove its runtime override and reveal environment/default configuration |

Thus `configure(level=None)` resets only the runtime global-level override. `configure()` does not reset existing state. `None` is a configuration operation, not a value accepted by the primitive level/boolean parsers.

The DSN key has one explicit exception to ordinary programmatic string validation: `configure(sentryDataSourceName="")`, including a whitespace-only string after trimming, stores a disabled-DSN override. It masks an environment DSN. `configure(sentryDataSourceName=None)` removes that override and may enable Sentry again from the environment. Enablement still depends solely on the effective DSN; no separate boolean flag exists.

For other string-valued programmatic options, reject empty/whitespace-only strings. `reloadEnvironment` must be a valid boolean and does not accept `None` as a reset operation.

Examples:

```python
configure(level="info", consoleEnabled=True)
configure(packageName="My Service")  # retains earlier runtime settings
configure(packageName=None)          # restores environment/automatic name
configure(sentryDataSourceName="")   # explicitly disables the owned provider
configure(sentryDataSourceName=None) # restores environment DSN, if present
```

### Precedence and validation

Resolve configuration in this order:

1. Normalize and validate every explicitly configured value in the environment snapshot and candidate runtime state, including values shadowed by another source. Empty environment values are absent.
2. Merge runtime over environment over defaults **per key and per exact logger name**.
3. Calculate the effective global level using section 4.
4. Resolve the logger hierarchy using section 5.
5. Apply each enabled provider's additional threshold using section 10.

Changing one key must not implicitly clear another. Given environment `DEBUGGING=true` and `LOGGER=warning`, `configure(level="info")` still yields `DEBUG`. `configure(debugging=False, level="info")` yields `INFO`.

An invalid environment `LOGGER=banana` remains an error even if `DEBUGGING=true` or a valid runtime level would otherwise take precedence. Invalid explicit Sentry settings, including DSN syntax and level, also fail validation when the effective provider is disabled. Checking whether the optional SDK is installed is required only when the effective provider is enabled.

Errors must identify the configuration key and source. Include offending values only when non-sensitive; DSNs must always be redacted, including chained exception messages and configuration representations.

Validate the entire candidate before changing active configuration. A failed update or environment reload preserves the previous configuration, environment snapshot, handlers, and clients. Publish the owned configuration as one consistent snapshot. Records already in progress may finish using the old snapshot; subsequent records use the new one. Do not close resources still used by in-flight records.

Environment reload replaces the complete environment snapshot, including removal of variables that are now absent, while preserving runtime overrides. Atomicity applies to the owned pipeline; do not claim a transaction across arbitrary concurrent changes made by the host to Python logging.

## 4. Normalization and global levels

### Environment normalization

Trim supported environment values before parsing. Missing, empty, and whitespace-only values all mean unconfigured. This special handling does not make `normalizeLogLevel("")` or `normalizeBoolean("")` valid programmatic parser calls.

Do not load `.env` files implicitly. Applications may populate their environment before initialization.

### Level parser

Implement one internal level normalizer and reuse it for global, package, and provider thresholds. Future adapters must reuse it too; those adapters are not deliverables now.

| Canonical level | Accepted text aliases | Numeric value |
| --- | --- | ---: |
| `CRITICAL` | `critical`, `crit`, `c` | 50 |
| `ERROR` | `error`, `err`, `e` | 40 |
| `WARNING` | `warning`, `warn`, `w` | 30 |
| `INFO` | `info`, `i` | 20 |
| `DEBUG` | `debug`, `d` | 10 |
| `NOTSET` | `notset`, `none`, `n` | 0 |

Text aliases are case-insensitive and trimmed. Accept all integer thresholds `0..50`, including nonstandard values such as `5`, `15`, and `35`, and trimmed ASCII decimal digit strings representing those values. Reject booleans despite their Python `int` ancestry, floats, signed/decimal/exponent strings, unsupported objects, and values outside the range. Invalid examples include `True`, `30.0`, `"+30"`, `"-1"`, `51`, `"verbose"`, and `""`.

The parser returns only a numeric threshold. Context determines what zero means:

- Global `0`: no additional minimum severity in the owned pipeline.
- Package/logger `0`: explicit inheritance, as defined in section 5.
- Provider `0`: no additional provider restriction.

Threshold configuration is separate from record severity. `logger.log(level, ...)` supports positive integer severities `1..50`; `0` is not an emitted severity. Preserve an incoming third-party record's numeric level, including values above `50`; do not reject an existing record because the configuration range is narrower. Preserve its level name where available.

### Boolean and precision parsers

Use one boolean normalizer for every boolean option. Accept actual booleans, integers `0` and `1`, and these case-insensitive, trimmed strings:

- True: `true`, `1`, `yes`, `y`, `on`.
- False: `false`, `0`, `no`, `n`, `off`.

Reject all other values, including other integers, floats, `None`, and non-empty invalid strings such as `maybe`. The configuration layer handles resets before calling this parser.

Duration precision accepts integers `0..6` or trimmed ASCII decimal digit strings in that range. Reject booleans, floats, and out-of-range values.

### Global decision table

Apply this table after source precedence. “Level” means the merged runtime `level` / environment `LOGGER` value, not an implicit `INFO` default.

| Effective `debugging` | Effective explicit level | Global threshold |
| --- | --- | --- |
| `True` | Missing or any valid value | `DEBUG` |
| `False` | Present | Parsed level |
| `False` | Missing | `ERROR` |
| Unconfigured | Present | Parsed level |
| Unconfigured | Missing | `INFO` |

These choices are intentional: explicit false differs from absence; true overrides only the global/default threshold and leaves package rules intact. In particular, `DEBUGGING=true` selects threshold `10`, even if `LOGGER=0` was supplied.

## 5. Package rules and hierarchy

Support:

```python
setPackageLevel("my_package", "debug")
setPackageLevel("requests", 30)
setPackageLevel("urllib3", "error")
resetPackageLevel("my_package")
```

Environment equivalent:

```text
LOGGER=info
LOGGER_PACKAGES=" my_package = DEBUG , requests = warn , urllib3 = 40 "
```

Logger names are trimmed but **case-sensitive**. Only level tokens are case-insensitive. Treat names as dot-separated paths; reject empty names, empty path segments, embedded whitespace, `,`, and `=`. Do not require every segment to be a Python identifier: names containing hyphens may be valid. Reserve the literal name `root` for global configuration; reject it as a package rule.

Parse `LOGGER_PACKAGES` as comma-separated `name=level` pairs with exactly one equals sign per pair. Reject empty entries, missing values, trailing commas, malformed names, invalid levels, and duplicate exact names after trimming. Do not silently choose the first or last duplicate. An entirely blank environment variable remains absent under section 4.

At each exact logger name, select its runtime entry if present; otherwise select its environment entry. Then search from the full record name through its dot-separated ancestors:

- The first selected nonzero rule wins.
- A selected zero rule masks any lower-precedence entry at that exact name, then continues searching at the parent.
- If no nonzero rule is found, use the effective global threshold.

Matching is by path segment: `foo` matches `foo.bar`, but never `foobar`. Specificity wins after per-name source merging: an environment `my_package.api=warning` still outranks a runtime `my_package=debug` for `my_package.api`.

For rules `my_package=info`, `my_package.database=warning`, and `my_package.database.query=debug`:

| Record name | Threshold |
| --- | --- |
| `my_package.api` | `INFO` |
| `my_package.database.connection` | `WARNING` |
| `my_package.database.query.builder` | `DEBUG` |

`setPackageLevel(name, 0)` stores an explicit runtime inheritance directive. `resetPackageLevel(name)` removes only the runtime entry for that exact name, without removing descendant entries. Resetting an absent runtime entry is a no-op.

For environment `LOGGER=info` and `LOGGER_PACKAGES="my_package=warning"`:

```python
setPackageLevel("my_package", "debug")  # DEBUG
setPackageLevel("my_package", 0)        # INFO: masks exact environment rule
resetPackageLevel("my_package")        # WARNING: environment rule visible again
```

Updates must be thread-safe, invalidate affected resolution caches, and apply to existing and future logger facades. Unrelated rules remain unchanged.

## 6. Standard logging integration and ownership

Build on `logging.LogRecord`, handlers, and filters. Preserve `LogRecord.name`, exception information, stack information, and caller attribution. Do not globally replace the logger class, record factory, or logging methods.

Install a single identifiable owned dispatch handler on the root logger. Route each accepted record to each enabled owned provider at most once. Do not attach the same dispatch path to both root and descendants. Repeated configuration must reuse/update the owned pipeline rather than stack handlers.

Apply hierarchy filtering in the owned handler/provider pipeline using the record name. An ancestor logger's level/filter is not reapplied to propagated records, so ancestor levels alone cannot enforce this specification. See the [Python logging reference](https://docs.python.org/3/library/logging.html#logging.Logger.propagate).

### Record creation versus provider filtering

To make default `INFO` output and package `DEBUG` overrides possible in a fresh application:

- With `manageRootLevel=True`, set the root logger's creation gate to `NOTSET` while the package is active; apply the actual global/package thresholds in the owned pipeline.
- With `manageRootLevel=False`, preserve the host root level. Document that it can prevent records from being created even when a package threshold would accept them.
- An explicit package rule authorizes setting that exact standard logger's creation gate to `1`, the lowest supported emitted severity, allowing the owned hierarchy filter to decide its threshold. Using `NOTSET` here would inherit potentially restrictive host ancestor levels. Do not rewrite unrelated or unconfigured descendant logger levels.
- Remember levels changed by the package. Restore a named gate when its exact rule disappears from both sources; restore the root gate when root management is disabled; restore all remaining managed gates on shutdown. Restore only if the current value still equals the last value installed by the package, so a detectable later host change is preserved.
- Entering root management or explicitly adding/changing a package rule authorizes its corresponding gate update. Reapplying unchanged settings or changing an unrelated option must not overwrite host levels modified since installation. Do not continuously enforce gates against host reconfiguration.

Existing host gates still matter: explicit levels on unconfigured loggers, `disabled`, `logging.disable()`, logger filters, and `propagate=False` can suppress records before the owned handler sees them. Do not bypass these host controls or promise to recover discarded records. Document these limits and show how the host can adjust the relevant logger explicitly. New ordinary loggers that inherit levels must work without special registration.

Facade calls may perform an early owned-threshold check, but must also respect the underlying standard logger's creation/propagation behavior. `isEnabledFor()` reports severity eligibility through the owned and standard logger level gates; it is not a guarantee of eventual provider delivery.

Changing a root or named logger's creation gate can change which records reach foreign handlers, even when the handler objects are untouched. Explain this process-wide effect and `manageRootLevel=False` for host-controlled applications. The [Python logging HOWTO](https://docs.python.org/3/howto/logging.html) describes these distinct logger and handler roles.

### Handler ownership

`rootHandlerPolicy="preserve"` is the default:

- Never remove, replace, close, or modify foreign handlers in this mode.
- Foreign handlers may produce additional output under their own configuration; owned thresholds do not filter foreign output.
- Disabling the owned console must leave Sentry and foreign handlers independent.

`rootHandlerPolicy="replace"` is explicit application opt-in to root-handler takeover and the sole exception to preservation:

- Detach existing foreign root handlers, retaining them for restoration. Do not modify or close them.
- This affects **all root handlers**, including file/network handlers; document that consequence clearly. Do not guess which custom handlers are console handlers.
- Leave descendant handlers untouched. Therefore root takeover cannot guarantee exclusive output from all third-party loggers.
- Restore detached handlers when leaving this mode or shutting down, without double-attaching them or removing handlers subsequently added by the host.
- Reapplying the same policy must not repeatedly detach newly added host handlers. Do not continuously enforce ownership against external reconfiguration.

Do not use `basicConfig(force=True)` or a destructive global reset. Only an explicit switch into replacement mode may detach foreign root handlers.

If both owned providers are disabled, the owned pipeline emits nothing and must not invoke a console fallback. Host output remains under host control.

## 7. Console output and source detection

The console provider is enabled by default and writes to `stderr`, keeping CLI result output on `stdout` usable. No colors or terminal-control sequences are required. Output must work in terminals, containers, and CI logs.

Use:

```text
TIMESTAMP | LEVEL | PACKAGE | DURATION | SOURCE | MESSAGE [| METADATA]
```

Example, with padding illustrative:

```text
2026-09-09 20:35:42.182Z | INFO     | My Package      |     - | my_package.api      | Application started
2026-09-09 20:35:42.419Z | WARNING  | My Package      |  0.9s | my_package.database | Database response was slow | durationMs=842
2026-09-09 20:35:43.021Z | ERROR    | My Package      |  1.3s | my_package.auth     | Authentication failed | userId=123
2026-09-09 20:35:43.552Z | CRITICAL | Payment Gateway | 12.4s | payment_gateway.api | Payment provider unavailable | provider="stripe"
```

The timed examples assume active operations with different start times; their durations are not intervals between log records. User metadata such as `durationMs` is independent of the computed duration column.

Use UTC by default, with milliseconds and a literal `Z`. `timestampFormat` is a documented `datetime.strftime` format applied to a timezone-aware UTC datetime; custom `%f` yields microseconds. Implement the default three-digit milliseconds explicitly rather than claiming `%f` produces them. Timestamp formatting is separate from monotonic duration measurement.

Use fixed documented minimum widths, expanding for longer values without truncating package/source names or changing a global width after each record. Left-align text and right-align duration. Omit the metadata separator when metadata is absent. Keep message and metadata escaping deterministic; escape embedded line breaks and terminal control characters in the record header. Render requested tracebacks/stack information as readable following lines.

### Source

- Named facades use their explicit logger name as `SOURCE`.
- Incoming standard records use `LogRecord.name`; do not replace it with an inferred application name.
- The global convenience logger resolves the calling module, skipping internal frames and respecting user `stacklevel`.
- For execution as `__main__`, prefer a meaningful `__spec__.name`, then the script file stem; use `__main__` if neither is available. Do not expose absolute paths in the source column.
- Preserve the actual call site's filename, line number, and function in the record independently of its displayed logger name.

### Package display name

Use the first segment of the effective source, split underscores/hyphens into words, and title-case the words. Examples: `my_package.api` → `My Package`, `payment_gateway.api` → `Payment Gateway`, and `n_log_forge` → `N Log Forge`.

This is a display-label heuristic, not Python distribution discovery. Do not scan installed distributions or the filesystem. An explicit `packageName` overrides the display label for the owned pipeline, including third-party records, while preserving their source/logger names.

Cache name transformations safely. Never cache the global logger's first caller as the source for later calls from other modules.

## 8. Timing contract

Every console record includes `DURATION`. Without an active operation, it is `-`. With an active operation, it is elapsed time since the **innermost** active operation started, captured when the record enters the owned pipeline, before any queue or provider work. Ordinary logging calls must not invent an operation duration.

Required APIs:

```python
with logger.timed("database_query") as timer:
    logger.info("Fetching rows")

@logger.timed("refresh_cache")
def refresh_cache():
    logger.info("Refreshing")

@logger.timed("fetch_user")
async def fetch_user():
    logger.info("Fetching")

# The same synchronous context manager is valid inside an async function,
# including across an await; it performs no asynchronous setup/cleanup.

handle = logger.startTimer("batch")
try:
    logger.info("Processing batch")
finally:
    elapsed_seconds = handle.stop()
```

`timed(name)` requires a non-empty operation name. It returns a context manager/decorator. Each entry/invocation must allocate independent timing state, including recursive or concurrent use of the same decorator. Preserve decorated function metadata and return values. Async decorators time the awaited body, not creation of the coroutine object. Generator and async-generator decorators are outside this release; reject their use clearly rather than timing generator creation.

The context manager yields a handle with a read-only `elapsedSeconds` property. `startTimer(name)` immediately enters the same kind of timing context and returns a handle with `stop()` and `elapsedSeconds`. `stop()` returns elapsed seconds and freezes the handle's elapsed value; repeated stops return that same value. An active explicit handle must be stopped in its starting context and in nesting order; misuse raises a clear error without corrupting context. Normal context exit stops its handle, including after an exception or cancellation.

Timing adds operation name and raw duration to internal structured context. It does not automatically emit start, completion, or failure records, change an application's return values, swallow exceptions, or override the severity of explicit logging calls. After an inner timer exits, logging resumes using the outer timer; after the last timer exits, duration is `-`.

Use a monotonic high-resolution integer clock such as `perf_counter_ns()`. Keep raw elapsed nanoseconds internally. For precision `p` in `0..6`, calculate ceiling-rounded units using integer arithmetic:

```text
quantum_ns = 10 ** (9 - p)
units = (elapsed_ns + quantum_ns - 1) // quantum_ns
```

Render `units / 10**p` using integer/string formatting with exactly `p` decimal digits and the `s` suffix. Do not convert through a binary floating-point rounding step. True zero renders `0.0s` at default precision; positive sub-tenth durations render `0.1s`.

| Raw seconds | Default display |
| ---: | ---: |
| 0.000 | `0.0s` |
| 0.001 | `0.1s` |
| 0.099 | `0.1s` |
| 0.100 | `0.1s` |
| 0.101 | `0.2s` |
| 0.842 | `0.9s` |
| 1.000 | `1.0s` |
| 1.001 | `1.1s` |
| 1.210 | `1.3s` |
| 2.000 | `2.0s` |
| 12.310 | `12.4s` |

### Context isolation and inheritance

Use context-local state, preferably immutable stack entries in `ContextVar`, with token restoration in `finally`. Do not share a mutable timing stack across requests, threads, or tasks.

Distinguish isolation from intentional context inheritance: child asyncio tasks copy the current context, and `asyncio.to_thread()` propagates it. A child can inherit a parent's operation start, but pushing/popping its own operations must not change the parent's stack. A copied context retains its inherited timing entry even after the parent exits; document how callers create a clean context for detached background work. Ordinary threads without copied context have independent timing state. See the [asyncio task and thread documentation](https://docs.python.org/3/library/asyncio-task.html) and [contextvars documentation](https://docs.python.org/3/library/contextvars.html).

A consumer thread must never look up the producer's timing context after enqueueing. Tests must use controlled clocks and explicit synchronization rather than sleep-based duration assertions.

## 9. Structured metadata and exceptions

Keep user metadata, core record fields, and internal operation context in distinct namespaces. Providers consume structured events, never parse rendered console strings.

For facade calls:

- `exc_info`, `stack_info`, `stacklevel`, and `extra` are control arguments.
- Non-control keyword arguments become metadata. Preserve user-defined `extra` attributes and expose them as metadata to the owned pipeline.
- Reject duplicate keys across `extra` and keyword metadata, collisions with standard `LogRecord` fields (including formatter fields such as `message` and `asctime`), and a documented internal reserved prefix such as `nlf_`.
- Require string metadata keys. Report invalid facade arguments with a clear `TypeError` or `ValueError` before dispatch. Do not silently overwrite data.
- User metadata stays nested when mapped to provider payloads, so a user key cannot replace a provider's top-level fields.

For incoming third-party records, extract custom attributes from a copy without mutating the original record or changing what foreign handlers observe. Handle unrelated third-party attributes gracefully; only facade argument validation should raise caller-facing collision errors.

Preserve JSON-compatible scalars, lists, and string-keyed mappings as structured values. Snapshot mutable metadata in the producer context before asynchronous dispatch. Define and document bounded depth, collection size, and string-length limits. Cycles, non-finite floats, unsupported objects, and objects with failing `repr`/`str` need safe, bounded, visibly marked fallback representations. Conversion failures must not crash the application or suppress otherwise valid console output.

Render console metadata in deterministic key order as `key=value` pairs, using compact JSON representations for values so strings, spaces, delimiters, and nested structures remain unambiguous. Never eagerly interpolate or serialize metadata for records rejected by known severity gates.

Exception usage:

```python
try:
    perform_operation()
except Exception:
    logger.exception("Operation failed", requestId="abc123")
```

Preserve exception type, message, traceback, chaining, source, metadata, and timing. Honor explicit `exc_info` and `stack_info` independently. Do not require callers to format traceback text or fabricate an exception when no exception information exists.

Never include the configured DSN in package-generated logs, configuration representations, or diagnostics. Do not dump environment variables or capture exception-frame local variables by default. Document that callers remain responsible for secrets they explicitly place in messages or metadata; do not claim arbitrary application content can be made secret-free automatically.

## 10. Providers and Sentry

The pipeline's immutable event snapshot must provide timestamp, numeric/name level, source/caller, package display name, message data, metadata, exception/stack data, and timing context. Defer expensive work until severity acceptance, then materialize the message and exception-derived remote payload in the producer context before asynchronous dispatch. Remote queues must not retain live mutable message arguments or traceback frames. Formatting/enrichment must not mutate a shared foreign `LogRecord`. Define a small typed internal provider interface for emit, flush, and close.

Every provider receives only records satisfying both thresholds:

```text
record.level >= resolved_logger_threshold
record.level >= provider_threshold
```

The owned console has no additional threshold (`0`). Sentry defaults to `ERROR`. Thus `LOGGER=warning` and `SENTRY_LEVEL=debug` permit only `WARNING+` records for Sentry. Providers cannot broaden logger eligibility or recover records already suppressed by standard logging.

### Sentry activation

Activation is determined solely by the **effective DSN after configuration merging**:

| Effective DSN | Result |
| --- | --- |
| Absent or explicitly disabled | Provider disabled; no SDK import/initialization required |
| Valid non-empty DSN | Enable the provider automatically |
| Invalid non-empty DSN in any configured source | Configuration error under section 3 |

Example:

```text
SENTRY_DATA_SOURCE_NAME=https://publicKey@example.ingest.sentry.io/123
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=1.0.0
SENTRY_LEVEL=error
```

Programmatic equivalent:

```python
configure(
    sentryDataSourceName="https://publicKey@example.ingest.sentry.io/123",
    sentryEnvironment="production",
    sentryRelease="1.0.0",
    sentryLevel="error",
)
```

Validate DSN structure locally, without DNS/network checks and without requiring the optional SDK merely to reject malformed syntax. Support SDK-compatible HTTP/HTTPS DSNs, including self-hosted hosts, ports, and path prefixes; do not hardcode Sentry Cloud hostnames. If an effective valid DSN requires a missing SDK, raise an optional-dependency error with `pip install "n-log-forge[sentry]"` instructions.

### Capture ownership and lifecycle

Use one explicit provider capture path with a provider-owned Sentry client. Do not replace, initialize, reconfigure, or close a host application's global Sentry client. Disable default/automatic integrations for the owned client so automatic logging capture cannot duplicate events or bypass thresholds. Keep this release to explicit message/exception events; Sentry Logs, breadcrumbs, unhandled-exception hooks, tracing, sessions, and profiling are outside scope. Consult the [official Sentry Python API](https://getsentry.github.io/sentry-python/api.html) for the selected supported SDK version and test the chosen isolation mechanism.

Make at most one owned event-capture attempt per accepted record, preserving logger name, numeric severity, metadata, and actual exception information. Delivery may fail under the policy below. For custom numeric severities, document a deterministic mapping to Sentry's supported severity names while retaining the original numeric value. Do not convert an exception to just a formatted message.

Pass explicit configuration to the owned client so unrelated SDK environment variables cannot activate it or add capture paths. Keep SDK debug output and collection of frame local variables disabled. Preserve operation context on each event without leaking it into a host/global scope.

Reuse the client when its construction settings are unchanged. Changing only a pipeline threshold or console setting must not recreate it. For construction-setting changes, prepare a replacement before publication, atomically switch owned snapshots, then drain and close the retired client after its in-flight users finish. Disabling the provider follows the same retirement rule. If preparation fails, retain the existing client/configuration.

The package guarantees no duplicate capture paths of its own. A separately configured host Sentry integration may also capture a record; document this coexistence limit instead of modifying host integrations.

### Failures and lifecycle APIs

Configuration and missing-dependency errors raise at initialization/reconfiguration. Runtime provider delivery, serialization, and transport failures must be isolated: a remote failure must not suppress console output, escape a normal logging call, or recursively log through the failing provider. Do not swallow application `KeyboardInterrupt`, `SystemExit`, or task cancellation as routine provider errors.

Keep remote network I/O off the ordinary emitting path using the SDK's transport where suitable. Avoid an additional queue unless justified. Any queue must be bounded, with a documented overflow policy and sanitized, rate-limited diagnostics/drop accounting. No unlimited buffering or unbounded retry loops. Synchronous console I/O can still block; async safety does not imply a fully nonblocking console.

Expose `flush(timeout=2.0) -> bool` and `shutdown(timeout=2.0) -> bool`. Validate finite, nonnegative timeout values and reject booleans. The timeout is a total budget across providers, not a new full timeout per provider. It bounds package-managed waits; do not synchronously enter potentially unbounded stream/transport cleanup on the caller's thread and then claim the deadline is guaranteed.

- `flush` waits up to the budget for currently queued owned work; return false when draining fails or times out. Completion does not prove remote durable delivery.
- `shutdown` stops accepting new owned work, detaches owned intake, restores owned logging changes as specified in section 6, and attempts bounded draining/cleanup. If work or cleanup remains at the deadline, return false and defer closing busy resources until their last in-flight user exits. A later shutdown may complete outstanding cleanup; never close resources beneath active users. Already-blocked external I/O cannot be forcibly cancelled.
- Serialize lifecycle transitions with configuration so retired cleanup cannot detach or close a restarted pipeline. Shutdown must be idempotent, including after a timed-out attempt.
- Neither method initializes an unused pipeline. After shutdown, facade logging methods drop records and `isEnabledFor()` returns false until explicit `configure(...)` restarts it. Timing APIs remain usable. Package-rule helpers may update retained runtime rules while stopped but do not restart or alter host logging. Restart retains configuration unless changed/reset/reloaded explicitly.
- Normal interpreter exit may attempt bounded best-effort shutdown. Do not promise delivery after crashes, forced termination, or network outages. Explain explicit flush/shutdown for short-lived CLI processes and workers.
- Initialize each worker process after process creation. Arbitrary reuse of a live pre-fork SDK client or cross-process queues is outside the supported contract.

## 11. Performance and concurrency

Use thread-safe immutable configuration snapshots or a similarly clear design. Do not hold a global configuration lock during formatting, provider I/O, or queue draining. Define lock ordering so reconfiguration and handler emission cannot deadlock. Keep retired resources valid for in-flight records.

For named facades, check eligible severity before expensive caller inspection, interpolation, traceback formatting, or serialization. For the global facade, resolve the caller before rejecting a record when a package-specific rule could lower the global threshold: global `INFO` must not discard `my_package`'s `DEBUG` record when `my_package=DEBUG`.

Cache normalized configuration and hierarchy resolutions. Invalidate on relevant updates and environment reload. Favor correctness over speculative optimization; avoid unsafe frame caches, unbounded caches keyed by arbitrary message data, and unnecessary provider work when disabled.

Concurrency support means independent logging/timing calls are safe and configuration snapshots are coherent. It does not guarantee total ordering across threads, processes, or remote delivery.

## 12. README and examples

The README must let developers use the package without reading implementation internals. Include:

- Base and Sentry-extra installation, supported Python versions, and a minimal quick start.
- Named/global facades, standard logging interoperability, lazy `%` formatting, metadata, exceptions, and all three timing forms, including async use.
- The configuration table, level aliases/range, boolean syntax, global decision table, environment-empty handling, and absence versus explicit `DEBUGGING=false`.
- Per-key source precedence, logger specificity, case-sensitive names, segment matching, runtime `NOTSET` versus reset, environment reload, and failed-update behavior.
- A noisy-dependency example using `urllib3`, plus third-party creation/propagation limitations and root-level side effects.
- Import/first-use behavior, cooperative handler preservation, explicit replacement consequences, console `stderr`, and disabling console independently of Sentry.
- Sentry DSN activation, programmatic disable versus reset, optional-dependency errors, event thresholds, host-client coexistence, and bounded flush/shutdown.
- Duration ceiling rounding, UTC/custom timestamps, copied-context timing behavior, metadata limits, and responsibility for caller-supplied secrets.
- Commands to run examples, checks, tests, and build artifacts locally.

Use placeholders clearly in explanatory prose. Do not put `DEBUGGING=<not configured>` or similar placeholders into runnable shell examples; absence means actually unset. Use dummy DSNs only. Keep examples and tables consistent with the tested implementation.

## 13. Acceptance tests and completion criteria

Tests must be isolated from the developer's real environment, root logging state, and Sentry account. Use fake transports/providers and controlled clocks; avoid network access and timing-sensitive sleeps. Restore global logging state after each test.

Cover at least:

| Area | Required acceptance cases |
| --- | --- |
| Packaging | Build/install the wheel; base import/use without Sentry; optional extra import; declared minimum Python version |
| Initialization | Passive import/logger lookup; eager/lazy setup; concurrent first use; failed setup rollback/retry; repeated configure without duplicate handlers |
| Parsing | Every alias and integer threshold `0..50`; mixed case/whitespace; invalid types including booleans-as-levels; empty environment values versus direct parser errors; precision boundaries |
| Global configuration | Every row in section 4; shadowed invalid values still fail; runtime precedence per key; omitted versus `None`; environment reload/removal; all-or-nothing failed updates |
| Hierarchy | Parent/child specificity; runtime parent versus environment child; case sensitivity; `foo` versus `foobar`; duplicate/malformed environment entries; zero rules; exact reset; unrelated-rule preservation |
| Standard logging | Ordinary third-party inherited levels; explicit package rule below a restrictive unconfigured ancestor; restrictive unconfigured child gates; propagated child records filtered at owned handler; `disabled`, `logging.disable()`, and `propagate=False`; custom incoming severities; no record mutation |
| Ownership | Preserve foreign handlers; root-level management opt-out; targeted level restoration; host changes respected; opt-in replacement/restoration; no duplicate owned dispatch; both providers disabled |
| Formatting/source | Required columns; UTC milliseconds/custom format; deterministic padding/escaping; long names; absent metadata; source versus display override; different global callers; `stacklevel`; `__main__` fallbacks |
| Metadata/exceptions | Lazy interpolation; controls reserved; `extra` preservation/collisions; safe type conversion and limits; cycles/broken repr; snapshot of mutable values; exception chains, traceback, and independent stack information |
| Timing | Every boundary in section 8; precision `0..6`; zero/no context; nested restore; explicit stop/misuse; sync/async decorators; recursion/concurrent reuse; exceptions/cancellation; thread/task isolation versus intentional inheritance |
| Sentry | Missing/blank/valid/invalid DSNs; self-hosted syntax; disable/reset; missing SDK only fails when enabled; no alternate enable flags; effective thresholds including provider zero; structured exception capture; no owned duplicates; host client unchanged; DSN redaction including chained errors |
| Provider lifecycle | Unchanged-client reuse; replacement/disable with in-flight records; rollback on setup failure; remote failure leaves console usable; recursive diagnostic protection; queue saturation if queued; bounded flush/shutdown, idempotency, restart, and process-local initialization |
| Concurrency | Coherent config snapshots during updates; no deadlocks under simultaneous logging/reconfiguration; no timing/metadata crossover between independent contexts |

Do not merely assert private implementation details. Exercise public behavior and the final provider-capture boundary. Include a small runnable sync/async example and test that README examples use valid public API calls.

The work is complete when the package implements these contracts, the relevant checks pass, distributions build successfully, and the README accurately describes actual behavior and limitations. Report the implemented files, validation performed, and any remaining gaps candidly. Do not silently weaken acceptance criteria to make tests pass.
