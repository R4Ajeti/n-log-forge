---
name: constant-management
description: Define, reuse, or review descriptive UPPER_SNAKE_CASE constants for fixed keys and values, especially when saving or serializing data. Use when adding stored fields, configuration keys, protocol values, or replacing magic literals.
---

# Constant Management

## Location and ownership

Use `core/constant/` at level 2, as defined by [n-layer-scaffold](../n-layer-scaffold/SKILL.md). Group definitions by capability or contract in singular, descriptive modules such as `<capability>_constant.<extension>`. In an established layout, follow that skill's adaptation rule instead of creating competing sources of truth.

Before adding a constant, find its current owner. Reuse an existing definition or library-provided constant with the same meaning. Equal literals with unrelated meanings need separate names; merge duplicates only when their contracts are the same.

## Required use and naming

- Every fixed key used to save, persist, cache, serialize, or construct a keyed record must use a named constant, even if used once. Use the same definition for reads, updates, deletions, and comparisons. Apply this to string and non-string keys.
- Every fixed value written through those operations must also use a named constant: statuses, discriminator values, defaults, sentinel values, and similar contract literals. Extract meaningful fixed values elsewhere, such as limits, retry counts, timeouts, and configuration names, rather than leaving magic literals.
- Dynamic keys and values remain runtime data: user text, generated identifiers, timestamps, calculated results, and configuration values are not constants. Name fixed prefixes, templates, and setting keys separately. In raw JSON, SQL, or other formats that cannot reference code constants, retain the required literal representation and verify it against the owning definition.
- Use `UPPER_SNAKE_CASE`. Make names as descriptive as necessary to convey the owning context, purpose, and role; prefer clarity over short names or arbitrary length limits. Include units when relevant and a type suffix, using the project's established suffix vocabulary (for example `_STR`, `_INT`, `_BOOL`). Define a consistent vocabulary if none exists.
- For example, `JOB_RECORD_PROCESSING_STATUS_KEY_STR`, `JOB_PROCESSING_STATUS_PENDING_VALUE_STR`, and `JOB_PROCESSING_RETRY_DELAY_SECONDS_INT` distinguish a stored field, its allowed value, and an interval. These are naming examples, not prescribed domain entities.

Language-neutral usage:

```text
JOB_RECORD_PROCESSING_STATUS_KEY_STR = "processing_status"
JOB_PROCESSING_STATUS_PENDING_VALUE_STR = "pending"

record[JOB_RECORD_PROCESSING_STATUS_KEY_STR] = JOB_PROCESSING_STATUS_PENDING_VALUE_STR
```

## Keep definitions inert

Constant modules contain immutable definitions only: no business logic, environment reads, I/O, runtime calculations, or mutable application state. Use language-supported immutable declarations/collections where available; keep runtime configuration and secrets in the configuration mechanism. A secret's setting name may be a constant, its secret value must not be.

Keep constant modules independent of application services and adapters so consumers can import them without dependency cycles. Do not add redundant aliases for schema-generated or library-owned definitions.

## Refactor without changing the contract

Preserve exact stored keys and values, including casing, types, and units, when replacing literals. Search related producers and consumers before renaming or merging constants; changing a persisted literal is a contract migration, not a cosmetic rename. Verify affected imports and behavior with the existing relevant checks, and report any literals that remain because the output format requires them.
