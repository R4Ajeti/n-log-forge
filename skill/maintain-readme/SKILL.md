---
name: maintain-readme
description: Create, simplify, review, or update a project README. Use for README requests and to assess documentation impact when implementation changes affect users, integrators, contributors, or operators.
---

# Maintain README

Keep the README accurate and easy to scan so a new reader can understand the project and complete its main workflow without reading source code.

## Establish the documentation contract

Inspect repository instructions, the existing README, and the current diff. Respect repository-specific requirements and requested file scope; use the verification table below to check factual claims.

Document the current supported state; do not present planned behavior as implemented or use the README as a changelog.

## Decide what needs updating

After an implementation change, assess whether readers need new information about:

- Purpose, scope, limitations, installation, dependencies, or compatibility.
- Public APIs, commands, input/output contracts, defaults, errors, or fallback behavior.
- Configuration, environment variables, provider setup, security, privacy, or credentials.
- Diagnostics, development workflows, architecture conventions, licensing, or support links.

Leave the README unchanged for internal refactors, formatting, private details, and test-only changes that do not alter a supported contract. Otherwise update the smallest relevant section, including dependent examples, and remove stale or contradictory statements. Merge overlapping sections instead of appending duplicates.

## Organize around the reader's first task

Adapt this order to the project; omit sections that add no value:

1. Project name, purpose, intended audience, and essential constraint.
2. Quick start with the shortest supported path to a useful result.
3. Installation and core usage or public API.
4. Configuration, optional integrations, important behavior, and limitations.
5. Diagnostics and troubleshooting.
6. Testing, development, and contributor architecture guidance.
7. License and support links.

Keep advanced usage and contributor details below basic usage. Link to maintained detail instead of copying it. Avoid empty headings, unnecessary tables of contents, decorative clutter, and manual freshness dates.

## Write useful examples and precise contracts

Use plain language, descriptive headings, short paragraphs, and consistent terminology. Define necessary domain terms once. Use lists for steps, tables for repeated option fields, and language-tagged code fences for examples.

The quick start should show only the necessary installation, canonical public import or command, one main operation, and a brief result explanation. State the working directory and prerequisites so commands are copyable. Move alternate providers, debugging, persistence, and other advanced variants to later sections.

For APIs, document exact public names, non-obvious accepted inputs, return shape, material defaults, important errors/fallbacks, and state or external side effects. Prefer a small example over an exhaustive API inventory.

For supported configuration, include purpose, required/optional status, relevant defaults, and whether values are secret. Explain how credentials are supplied and whether they can enter logs or persisted state when relevant.

Use safe sample data and obvious placeholders for credentials and private endpoints. Never publish real tokens, cookies, credentials, private URLs, or production data. Keep security and compatibility constraints even when shortening the text; place warnings beside the affected step.

## Verify the result

Cross-check claims against their sources:

| README content | Verify against |
| --- | --- |
| Installation, package names, repository URLs, supported versions | Package metadata and CI |
| Imports, signatures, behavior, defaults, return values | Public exports, implementation, and tests |
| Settings and environment variables | Configuration definitions and runtime lookups |
| Test/build/development commands | Tool configuration and scripts |
| License and support links | License files and repository metadata |

Run documented commands when practical and safe. Prefer offline or mocked verification if execution would need live providers, credentials, paid resources, or production access. Distinguish commands actually run from claims checked only against source. Label variable output as illustrative or describe its shape.

Review the complete README for old names, contradictory statements, broken links, invalid Markdown, and duplicated setup. Confirm the quick start still works as a coherent sequence and that required behavioral, security, and limitation notes survived restructuring.

In the handoff, mention documentation changes, or why none were needed, when useful; report any material verification limits.
