---
name: n-layer-scaffold
description: Create or adapt an N-layer project scaffold with explicit directory levels and responsibility boundaries. Use for initial structure or a requested architecture reorganization, in any language or repository.
---

# N-Layer Scaffold

## Choose the root and scope

Inspect repository instructions, package/build metadata, entry points, and existing layout. Resolve `project_root` to the target project root; in a monorepo, identify the selected project explicitly. That path is **level 0**, regardless of its absolute filesystem depth. Each child directory adds one level.

Use the layout below for a new scaffold. When adapting an existing project, map its equivalents before moving files; retain framework-required locations and public imports unless migration is requested. Derive module names and extensions from the actual capability and language, never from another repository's examples.

## Directory contract

```text
<project_root>/           # level 0
├── core/                 # level 1: application implementation
│   ├── constant/         # level 2
│   ├── helper/           # level 2
│   ├── proxy/            # level 2
│   ├── service/          # level 2
│   └── repo/             # level 2
├── test/                 # level 1
│   ├── constant/         # level 2
│   ├── helper/           # level 2
│   ├── proxy/            # level 2
│   ├── service/          # level 2
│   └── repo/             # level 2
└── raw/                  # level 1: when proxy examples are needed
    └── proxy/            # level 2
```

`constant/` is the first listed child of `core/`, at level 2. Use singular names for newly introduced architectural directories and modules; preserve language/framework naming requirements. Add package markers such as Python `__init__.py` only where the chosen packaging model needs them.

Test groups mirror their counterparts under `core/`. Use the repository's test runner naming conventions rather than assuming Python.

## Architectural meaning

Directory levels measure nesting, **not dependency rank or deployment tiers**. N-layer architecture separates responsibilities; N is determined by the application, not by the number of folders. Several logical layers can run in one process. [Microsoft: N-tier architecture](https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/n-tier).

Use [service-boundary-review](../service-boundary-review/SKILL.md) for service, domain, repository, proxy, and helper responsibilities and dependency rules. Entry points and domain models may use existing locations or get dedicated modules when needed; do not force them into helpers just to fit this tree. Larger projects may group by capability and layer within each group. [Fowler: Presentation Domain Data Layering](https://martinfowler.com/bliki/PresentationDomainDataLayering.html).

The tree is this skill set's folder convention, not a layout mandated by those sources. It does not enforce dependencies or require separate deployments; follow one consistent dependency model when mapping the application.

## Scaffold and verify

1. Create the required directory skeleton and only the capability-named modules needed by the requested scope. Do not invent provider-specific filenames, branches, packages, or integrations.
2. In scaffold-only work, keep declarations and placeholders clearly incomplete; add no operational business logic, network calls, provider SDK integration, credentials, or secret configuration. Real implementation requires implementation scope.
3. Apply [constant-management](../constant-management/SKILL.md) when defining keys or fixed values. For deferred unit tests, use [test-placeholder](../test-placeholder/SKILL.md). For implemented or changed proxies, use [proxy-example-contract](../proxy-example-contract/SKILL.md); it owns the raw artifact filenames. Scaffold examples, if requested, must be labeled as proposed rather than verified responses.
4. Check package discovery/imports, module placement, and requested file moves against the build configuration. Report the final tree rooted at level 0, created or moved files, and remaining placeholders.
