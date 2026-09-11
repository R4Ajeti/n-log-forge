# Finalize Packaging, CI, Examples, and Documentation

Parent specification: [`000001_build_reusable_structured_logging_package_with_sentry_support.md`](000001_build_reusable_structured_logging_package_with_sentry_support.md)

## Outcome and scope

Verify and maintain the already implemented distribution metadata, typed-package
markers, wheel/source builds, CI workflow, runnable examples, raw fixtures, README, and
whole-project quality gates. This is the final integration and release-readiness slice;
it does not publish a release.

The owner-required layout is authoritative: keep both `core/` and `n_log_forge/` at the
repository root. The wheel ships both, but only `n_log_forge` is the supported consumer
API; `core` is an internal implementation package. Do not move `core/` into `src/`.

This plan covers parent sections 1, 12, and 13 and integrates the results of plans
000002 through 000004.

## Implemented baseline

- `pyproject.toml` defines distribution `n-log-forge`, version metadata, Python
  `>=3.14`, base dependency-free behavior, the optional `sentry` extra, the `dev` extra,
  Hatchling wheel/sdist contents, Ruff, pytest, and mypy configuration.
- The wheel contains `n_log_forge`, root-level internal `core`, and both `py.typed`
  markers. The sdist includes source, tests, examples, raw fixtures, README, license,
  project metadata, and CI workflow.
- `.github/workflows/ci.yml` runs on the declared minimum Python version and performs
  install, Ruff, mypy, pytest, build, and a clean base-wheel smoke test without Sentry.
- `example/sync_async.py` exercises the real public API in synchronous and asynchronous
  code without external services.
- `raw/` holds complete console and Sentry request/input/output fixtures used to inspect
  the final provider boundaries.
- `README.md` documents installation, API, configuration semantics and tables,
  hierarchy, logging ownership, console/event behavior, timing, metadata/security,
  Sentry isolation, lifecycle/process guidance, examples, development commands, layout,
  and license.
- The current implementation has passed full Ruff, mypy, pytest, coverage, distribution
  build, archive inspection, clean wheel installation, and base use with Sentry absent.

## Requirement coverage

| Area | Required behavior | Primary artifact/check |
| --- | --- | --- |
| Metadata | Correct name/version/Python range/extras/build backend | `pyproject.toml`, built `METADATA` |
| Package layout | Root `core`, supported `n_log_forge` facade, typed markers | wheel archive and clean install |
| Base install | Import/use without Sentry installed | isolated wheel smoke environment |
| Optional install | Declared compatible Sentry extra | `pyproject.toml`, CI/full environment |
| Source archive | Sources, tests, examples, fixtures, docs, license, CI included | sdist archive inspection |
| CI | Minimum Python, lint, types, tests, build, base smoke | `.github/workflows/ci.yml` |
| Examples | Runnable sync/async public API, no live service | `example/sync_async.py` |
| Documentation | Every parent section 12 topic matches tested behavior | `README.md` review plus public tests |
| Final quality | Full suite, no network, isolated global state, build/install success | local verification sequence |

## Verification plan

1. Review project metadata, optional dependency bounds, package inclusion rules, typed
   markers, license/readme references, and declared minimum Python version.
2. Run the complete Ruff, mypy, and pytest suites from the project environment. Treat
   warnings, collection omissions, network attempts, environment leakage, and restored
   global-state failures as real defects.
3. Run the sync/async example and compare its behavior with README examples and the
   seven-name public API.
4. Build fresh wheel and sdist artifacts, inspect their file lists and metadata, and
   reject missing packages, markers, docs, fixtures, or accidental local files.
5. Create an isolated temporary environment, install only the built wheel without
   dependencies, prove `sentry_sdk` is absent, import the public facade, log a record,
   and call package-rule/configuration/lifecycle APIs.
6. In the full optional environment, verify the Sentry extra imports and provider tests
   remain transport-isolated.
7. Check that CI reproduces the same sequence on Python 3.14 and uses the built wheel for
   the base-install smoke test rather than the source checkout.
8. Audit every parent section 12 documentation item against actual signatures, defaults,
   decision tables, limits, side effects, failure behavior, and examples.
9. Confirm README clearly distinguishes supported `n_log_forge` imports from the shipped
   internal root `core` layout and explains why host logging/Sentry coexistence has
   process-wide limits.
10. Produce a final report listing implemented files, exact check results, build artifact
    names, the root-layout decision, and any remaining gap. Do not publish artifacts.

## Acceptance criteria

- `python -m ruff check .`, `python -m mypy`, and `python -m pytest -q` all succeed.
- A clean `python -m build` produces both wheel and sdist with valid metadata.
- The base wheel installs and its public API works in an environment where Sentry is not
  installed.
- Both `py.typed` markers and all required runtime modules exist in the wheel; tests,
  examples, raw fixtures, README, license, CI, and project metadata exist in the sdist.
- The example runs without a network connection and uses only documented public calls.
- CI validates the minimum supported Python version and the same release-readiness gates.
- README describes the implemented behavior, limitations, root-level `core` decision,
  development commands, and package lifecycle without contradicting tests.
- User-owned unrelated working-tree files are preserved, and no release is uploaded or
  live Sentry project contacted.

## Commands

```bash
python -m ruff check .
python -m mypy
python -m pytest -q
python example/sync_async.py
python -m build
python -m zipfile -l dist/n_log_forge-*.whl
python -m tarfile -l dist/n_log_forge-*.tar.gz
```

Perform the base-wheel smoke test from outside the repository so imports cannot fall
back to the working tree. Remove only the explicitly created temporary environment when
finished. Report any parent-specification gap candidly rather than weakening the check.
