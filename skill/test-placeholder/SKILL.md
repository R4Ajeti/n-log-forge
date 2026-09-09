---
name: test-placeholder
description: Add explicit placeholder tests while scaffolding unimplemented behavior or when deferred tests are requested. Do not replace working tests or treat placeholders as verification of implemented behavior.
---

# Test Placeholder

Record intended behavior without claiming it already works. Use this skill only for scaffolding or explicitly deferred tests; implemented behavior that needs verification requires meaningful executable tests.

## Placement and intent

Follow the repository's test framework, discovery rules, and naming conventions. Mirror logical source groups under the test root. For the N-layer scaffold, use the mapping in [n-layer-scaffold](../n-layer-scaffold/SKILL.md) instead of duplicating its directory layout here.

Name each placeholder for an observable behavior, such as returning eligible records, excluding failed resources, saving status changes, or rejecting invalid input. Describe the expected result and the missing implementation or dependency that prevents testing it now.

## Honest, isolated placeholders

- Prefer an explicitly skipped test with a specific reason when implementation is absent.
- Use an expected-failure marker only for a concrete executable assertion of known missing behavior. Make unexpected success fail the suite where the framework supports it, and constrain the expected failure when possible so unrelated errors are not hidden. If the framework cannot express that intent reliably, use a skip.
- Do not create empty passing tests, unconditional success assertions, or broad exception handlers that disguise failures. Never weaken existing executable tests to make a scaffold pass.
- Keep placeholder discovery and execution offline, independent of credentials, and free of live provider/cloud calls. Avoid network or credential requirements in module imports and fixtures as well as test bodies.
- When the behavior is implemented, replace the placeholder with a meaningful test and remove its skip/expected-failure marker.

Run collection or the relevant offline test command when feasible to confirm placeholders are reported as skipped or expected failures. In the handoff, list created test files, identify which tests remain placeholders, and distinguish collection success from verified application behavior.
