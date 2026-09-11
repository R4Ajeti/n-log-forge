# Finalize Sentry Delivery and Runtime Lifecycle

Parent specification: [`000001_build_reusable_structured_logging_package_with_sentry_support.md`](000001_build_reusable_structured_logging_package_with_sentry_support.md)

## Outcome and scope

Verify and maintain the already implemented optional Sentry provider, immutable event
mapping, isolated owned client, provider replacement, delivery-failure containment,
flush/shutdown/restart lifecycle, and concurrency guarantees. All tests must remain
network-free and must not modify a host application's Sentry client.

This plan covers parent sections 10 and 11 plus the Sentry, provider-lifecycle, and
concurrency acceptance cases from section 13.

## Implemented baseline

- Sentry is enabled solely by an effective non-empty `SENTRY_DATA_SOURCE_NAME` /
  `sentryDataSourceName`; unrelated SDK environment variables and an imagined enable
  flag cannot activate it.
- DSNs are validated locally before optional-SDK import and support HTTP/HTTPS,
  self-hosted ports, and path prefixes.
- Missing SDK errors occur only for an enabled valid DSN and identify the
  `n-log-forge[sentry]` installation command.
- The provider constructs an isolated `sentry_sdk.Client` with explicit DSN/settings,
  default integrations disabled, no global hub mutation, no frame locals, and no SDK
  debug mode.
- Immutable events map to one explicit `capture_event` attempt with structured metadata,
  source/caller data, original numeric severity, deterministic Sentry severity, timing,
  and structured exceptions.
- SDK-internal logger records are not sent back into the owned Sentry provider, avoiding
  recursive delivery loops while leaving console handling available.
- Construction-equivalent configurations reuse a client. Replacements are prepared
  before atomic publication and retired only after in-flight users release them.
- Runtime provider exceptions are isolated from normal logging and other providers;
  `KeyboardInterrupt`, `SystemExit`, and cancellation are not swallowed as routine
  delivery errors.
- Drop/failure accounting is bounded and saturating; tests use fake clients/transports
  and raw expected-event fixtures without contacting Sentry.
- `flush()` and `shutdown()` validate one finite nonnegative total budget, run blocking
  cleanup outside the caller's deadline-sensitive thread, support timeout/retry, and do
  not initialize an unused pipeline.
- Shutdown detaches intake, restores logging ownership, defers busy cleanup, is
  idempotent, and permits explicit restart with retained configuration. Interpreter exit
  performs bounded best-effort shutdown.

## Requirement coverage

| Area | Required behavior | Primary implementation/tests |
| --- | --- | --- |
| Activation | Effective DSN only, blank disable, reset, invalid/missing dependency paths | `core/service/configuration.py`, `core/proxy/sentry.py`, related tests |
| Client ownership | Isolated explicit client, no global host mutation, integrations disabled | `core/proxy/sentry.py`, `test/proxy/test_sentry.py` |
| Event mapping | One structured capture path, exception fidelity, custom severity mapping | `core/proxy/sentry.py`, `raw/sentry_*`, `test/proxy/test_sentry.py` |
| Thresholds | Logger threshold and provider threshold must both accept | `core/service/runtime.py`, `test/service/test_runtime.py` |
| Replacement | Reuse unchanged clients; prepare/switch/retire around in-flight records | `core/service/runtime.py`, `test/service/test_runtime.py` |
| Failure isolation | Console remains usable, no recursive Sentry loop, base exceptions propagate | `core/service/runtime.py`, `test/service/test_runtime.py` |
| Lifecycle | Total timeout budget, bounded cleanup, detach/restore, retry/idempotency/restart | `core/service/runtime.py`, public lifecycle tests |
| Concurrency | Coherent snapshots, lock-safe logging/configuration, valid retired resources | `core/service/runtime.py`, stress-oriented tests |

## Verification plan

1. Test missing, blank, explicitly disabled, reset, malformed, cloud-style, self-hosted,
   port, and path-prefix DSNs without DNS or transport access.
2. Confirm invalid values are rejected even while shadowed/disabled, all DSN diagnostics
   and chained exceptions are redacted, and no configuration representation exposes a
   credential-bearing DSN.
3. Test the missing-extra path with imports controlled so it fails only when a valid
   effective DSN actually enables the provider.
4. Instantiate the supported real SDK client only with a no-network fake transport and
   inspect its options. Prove the current global/host client is unchanged before and
   after owned initialization, emission, replacement, and shutdown.
5. Compare captured message, logger, timestamp, package, caller, metadata, operation,
   duration, numeric severity, mapped severity, stack, and chained exception structures
   with the checked-in raw fixture.
6. Exercise global/package/provider thresholds, including zero and custom numeric
   severities. Confirm providers never broaden record eligibility.
7. Verify exactly one owned capture attempt per accepted record and no recapture of the
   SDK's own diagnostic logger records.
8. Inject construction, serialization, emission, flush, and close failures. Confirm
   rollback/reuse rules, console continuity, normal-call isolation, bounded counters,
   and propagation of non-routine base exceptions.
9. Hold provider leases open while replacing, disabling, shutting down, timing out, and
   restarting. Confirm resources are never closed beneath in-flight users.
10. Run synchronized concurrent logging and reconfiguration repeatedly. Confirm no
    deadlock, duplicate handler/client path, torn snapshot, or cleanup of a new pipeline
    by an older lifecycle transition.

## Acceptance criteria

- Base installation imports and logs without importing Sentry; the optional dependency
  is needed only for an effectively enabled provider.
- The package never initializes, replaces, configures, or closes the host/global Sentry
  client and disables automatic capture paths on its owned client.
- Every accepted record creates at most one owned Sentry capture attempt and retains the
  required structured exception/metadata/timing fields.
- DSNs never appear in package-generated errors, chained messages, logs, or object
  representations.
- Provider failure cannot suppress console delivery, escape an ordinary logging call,
  or recursively enter the same failing Sentry path.
- Configuration replacement and lifecycle operations preserve in-flight safety and use
  a single validated timeout budget.
- Shutdown is bounded, retryable, idempotent, restores owned logging changes, and only
  explicit configuration restarts the stopped pipeline.
- Tests perform no real network operation and leave process-global logging/Sentry state
  exactly as they found it.

## Commands

```bash
python -m pytest -q \
  test/proxy/test_sentry.py \
  test/service/test_configuration.py \
  test/service/test_runtime.py \
  test/test_public_package.py
python -m ruff check core n_log_forge test
python -m mypy
```

Report any gap against the parent specification explicitly. Do not use the global Sentry
initializer or a live DSN as a shortcut for exercising the owned provider.
