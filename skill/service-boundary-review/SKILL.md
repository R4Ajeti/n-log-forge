---
name: service-boundary-review
description: Design, implement, refactor, or review application services and the boundaries between domain rules, repositories, external proxies, and helpers.
---

# Application Services and Boundary Review

An application service exposes a meaningful use case and coordinates its execution.

## Establish scope

- Identify the requested use cases, their callers, existing architecture, and externally observable contracts before changing boundaries.
- For a review request, inspect and report findings; implement fixes only when the user's request also authorizes them.
- Follow [n-layer-scaffold](../n-layer-scaffold/SKILL.md) for directory layout and [constant-management](../constant-management/SKILL.md) for constant ownership and naming. Apply these conventions when the task adopts that scaffold; map responsibilities to existing modules otherwise.

## Application-service responsibilities

- Expose operations in the application's language, with explicit inputs, results, and failure outcomes, reusable across callers such as HTTP handlers, commands, and jobs.
- Coordinate input validation, use-case authorization, data loading, domain operations, persistence, and external interactions in the required order. Keep transport parsing and response serialization at the transport boundary.
- Define the transaction boundary and coordinate commit or rollback through repository/unit-of-work abstractions; do not embed database operations in the service.
- Own workflow policy where the use case needs it: choose an eligible external adapter, decide when a workflow retries or falls back, request failure/unavailable state transitions, and return an explicit unavailable outcome when no option remains.
- For side-effecting workflows, define bounded retries, idempotency, and partial-failure handling where needed. A local database transaction cannot roll back an external call; use the project's supported compensation or reliable-delivery mechanism when consistency requires it.
- Keep state local to an invocation unless task progress is explicitly persisted. Return application-level outcomes without leaking credentials, storage handles, or provider-specific implementation details.

## Responsibility boundaries

| Owner | Belongs here | Keep elsewhere |
| --- | --- | --- |
| Domain objects / policies / domain services | Business invariants, eligibility rules, calculations, and valid state transitions; domain services handle rules that do not naturally belong to one entity/value object. | Transport, database, and provider implementation details; use-case sequencing. |
| Repository | Persistence queries, mapping, storage SDK/driver calls, and technical concurrency controls behind application-facing contracts. | Business decisions and calls to unrelated external provider proxies. A remote database is still persistence. |
| External proxy / adapter | Provider requests, authentication mechanics, serialization, response/error translation, and bounded transport-level retries. | Business eligibility, workflow fallback, and application persistence. Avoid duplicated retry loops across layers. |
| Helper | Pure, deterministic, reusable transformations independent of the application domain and provider. | Business decisions, provider behavior, secrets, persistence, or network I/O. |

In an existing simple transaction-script design, keep rules cohesive and separable; do not impose a full domain model merely to satisfy a folder convention. Extract a domain policy when reused rules or complexity justify it.

Keep dependencies acyclic: services do not depend on entry points, and repositories, proxies, and helpers do not call back into application services. In traditional layering, services may depend on repository/proxy modules. In Clean/Hexagonal designs, inner layers own the contracts and outer adapters implement them; wire concrete dependencies at the composition root. Preserve the project's chosen model rather than treating runtime call direction as source-import direction.

## Implement or refactor

1. Trace the use case from entry point to effects and identify which owner makes each decision. Prefer focused service operations over a service with unrelated workflows.
2. Define or reuse repository/proxy contracts in application terms. Inject dependencies using the project's conventions so orchestration can be exercised without live providers or databases.
3. Move misplaced behavior to its owner, updating callers and imports while preserving public behavior unless a contract change was requested. Avoid creating wrapper classes that only rename an existing call without providing a needed boundary.
4. Exercise relevant existing checks and add focused verification where the behavior warrants it: success, denied/invalid operations, unavailable dependencies, transaction failure, and duplicate execution when retries are involved. Use substitutes for external dependencies unless live integration is explicitly part of the task.

## Review and delivery

- Inspect implementation and dependency usage, not folder names alone. Trace at least the requested use case's success and failure paths.
- Report an overall **pass/fail** for the inspected scope, with file/symbol evidence for each violation, its practical consequence, and the appropriate owner.
- List recommended refactor steps and specific files to move or rename; use “none” when no move is needed. Distinguish confirmed violations from unverified areas.
- After authorized implementation, summarize the actual changes, verification performed, and any remaining boundary violations or limits.

## Design basis

- [Fowler: Service Layer](https://martinfowler.com/eaaCatalog/serviceLayer.html) establishes shared application operations, transaction coordination, and responses across different callers.
- [Microsoft: Application layer](https://learn.microsoft.com/en-us/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/ddd-oriented-microservice#the-application-layer) separates thin use-case coordination from domain rules and allows simpler designs for simple CRUD applications.
- [Microsoft: Domain and application services](https://learn.microsoft.com/en-us/azure/architecture/microservices/model/tactical-domain-driven-design#domain-and-application-services) distinguishes application orchestration from domain rules spanning entities. The concrete ownership rules above apply these principles to this skill collection.
