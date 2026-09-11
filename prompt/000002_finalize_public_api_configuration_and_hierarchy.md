# Finalize the Public API, Configuration, and Logger Hierarchy

Parent specification: [`000001_build_reusable_structured_logging_package_with_sentry_support.md`](000001_build_reusable_structured_logging_package_with_sentry_support.md)

## Outcome and scope

Verify and maintain the already implemented public facade, lazy initialization,
configuration normalization, package rules, and standard-library logging ownership.
Fix any regression found by the checks below without expanding the seven-name public API.

The repository layout deliberately follows the project-owner requirement that `core/`
remain at the repository root. The importable `n_log_forge/` facade also remains at the
root and delegates to that internal package. Do not migrate either package into `src/`.

This plan covers parent sections 2 through 6 and the corresponding initialization,
parsing, hierarchy, standard-logging, and ownership acceptance cases from section 13.
Sentry delivery, rendering, packaging, and documentation are owned by later plans.

## Implemented baseline

- `n_log_forge/__init__.py` exports exactly `logger`, `getLogger`, `configure`,
  `setPackageLevel`, `resetPackageLevel`, `flush`, and `shutdown` through `__all__`.
- Logger facades support standard severity methods, lazy `%` interpolation, control
  arguments, structured metadata, timing methods, `warn()` compatibility, and live
  configuration updates.
- Initialization is lazy, thread-safe, retryable after failure, and does not mutate
  root logging state on import or logger lookup.
- Configuration uses immutable snapshots and distinguishes omitted arguments from
  explicit `None` resets.
- Environment values are read once, can be atomically reloaded, and are validated even
  when shadowed by runtime overrides.
- Level, boolean, duration-precision, DSN, package-name, and package-rule normalization
  use typed helpers and source-aware errors.
- Exact-name runtime rules merge over environment rules before ancestor resolution;
  zero is an inheritance directive rather than a deletion.
- One owned root dispatch handler applies the hierarchy threshold. Root and named
  creation gates are restored conservatively, preserving later host changes.
- Preserve/replace handler policies, host controls, shutdown detachment, and restart
  behavior have deterministic tests.

## Requirement coverage

| Area | Required behavior | Primary implementation/tests |
| --- | --- | --- |
| Public facade | Seven top-level names, named facade reuse, future updates visible | `n_log_forge/__init__.py`, `core/service/facade.py`, `test/test_public_package.py`, `test/service/test_facade.py` |
| Initialization | Passive import, eager/lazy setup, one concurrent pipeline, rollback/retry | `core/service/runtime.py`, `test/service/test_runtime.py` |
| Configuration | Per-key precedence, omitted/reset distinction, atomic validation/reload | `core/service/configuration.py`, `test/service/test_configuration.py` |
| Normalization | All aliases, numeric levels `0..50`, strict booleans and precision | `core/helper/normalization.py`, `test/helper/test_normalization.py` |
| Hierarchy | Exact-source merge, ancestor specificity, zero masking, exact reset | `core/service/configuration.py`, `test/service/test_configuration.py` |
| Logging ownership | One owned handler, host-handler policy, creation gates and restoration | `core/service/runtime.py`, `test/service/test_runtime.py` |

## Verification plan

1. Confirm importing `n_log_forge` and acquiring a logger leave root handlers, levels,
   logger classes, record factories, and Sentry state untouched.
2. Exercise every public facade method, standard control argument, metadata validation
   path, named-logger cache path, and post-configuration update path.
3. Exercise every row of the global-level decision table and every valid/invalid parser
   boundary, including booleans-as-integers and shadowed invalid environment values.
4. Verify omitted arguments retain state, `None` reveals environment/default state,
   blank DSN is the documented disable override, and failed updates preserve the full
   prior snapshot and owned resources.
5. Verify package-name grammar, environment-map duplicates, case sensitivity, segment
   matching, specificity, runtime/environment merging, zero inheritance, and reset.
6. Verify root and named creation gates, foreign handlers, host filters, `disabled`,
   `logging.disable()`, `propagate=False`, incoming custom severities, and restoration.
7. Run simultaneous initialization, logging, package updates, and reconfiguration with
   explicit synchronization; reject deadlocks, duplicate dispatch, and torn snapshots.

## Acceptance criteria

- The documented seven-name import works and no additional non-private facade symbol is
  exposed accidentally.
- Import and logger lookup remain side-effect free; first use/configuration creates one
  reusable owned pipeline.
- All normalization, source precedence, reset, global decision-table, and hierarchy
  cases match the parent specification exactly.
- A failed initialization or update changes no active state and a subsequent retry can
  succeed.
- Existing facades see successful updates without reacquisition.
- Host logging controls are neither bypassed nor continuously overwritten.
- Repeated configuration never stacks owned handlers, and owned gates/handlers restore
  safely on shutdown.
- `core/` remains a root-level internal package and `n_log_forge/` remains the supported
  consumer import.

## Commands

```bash
python -m pytest -q \
  test/test_public_package.py \
  test/helper/test_normalization.py \
  test/service/test_configuration.py \
  test/service/test_facade.py \
  test/service/test_runtime.py
python -m ruff check core n_log_forge test
python -m mypy
```

Report any gap against the parent specification explicitly. Do not weaken an assertion
or broaden the public API merely to make a check pass.
