---
title: "Craig Architecture Python Guidance"
created_date: 2026-11-21
update_date: 2026-11-21
status: APPROVED
tags: [python, src-layout, domain-types, protocols, dependency-injection, testing, module-cohesion]
---

# Craig Architecture Python Guidance

This supplement applies [Craig Architecture](Craig-Architecture.md) to Python. Project-specific runtime versions and packaging remain with the active project configuration and implementation task.

## Package and Repository Structure

Prefer an installable `src/<package>/` layout with tests outside the production package. Keep repository-level documentation, CI, and scripts separate from runtime modules.

Organize code by responsibility and domain concern. Layer packages such as `domain`, `services`, `ports`, and outer adapters are useful when they express actual boundaries; an empty package hierarchy is not a prerequisite for a prototype.

Each independently packaged application or library owns its dependencies and build configuration. Shared code should have an explicit package boundary when justified. Avoid cross-application private imports and ad hoc `PYTHONPATH` wiring.

## Types and Boundary Translation

Prefer standard-library classes, dataclasses, enums, and explicit validation for core domain concepts. Use typed, focused contracts with system vocabulary.

Transport validation models, ORM records, and provider DTOs belong at their respective boundaries. Pydantic may validate inputs or serialization without becoming the default internal domain model. Map external records into domain-owned types before using them for core reasoning.

An exploratory structure can remain temporarily colocated with orchestration if it is easy to extract and does not acquire outward dependencies in the core.

## Ports and Public Surfaces

Prefer `typing.Protocol` for narrow capability contracts. Use an abstract base class when shared behavior or nominal semantics provides concrete value. Runtime protocol inspection should be introduced only when required.

Define contracts with the inner consumer. Keep interfaces focused on the capabilities that consumer needs.

Use thin, side-effect-free `__init__.py` files for curated public exports. Internal modules can import concrete sibling modules directly; routing every internal import through package exports often creates circular dependencies.

## Wiring and Import Safety

Supply dependencies through constructors or function parameters and compose implementations at entry points, bootstrap functions, or test setup. Keep framework-specific dependency mechanisms outside domain and service code.

Imports should not establish network connections, open a live database, start an application, or construct provider clients as incidental side effects.

Treat circular imports as a structural warning. Consider moving a shared concept inward, extracting a contract, or splitting responsibility. Type-only imports and postponed annotations can solve genuine typing concerns; local imports must not conceal reversed dependencies.

## State and Error Behavior

Express state transitions, allowed operations, failure outcomes, and units clearly. Keep source state distinct from cached observations or persisted representations. Define deterministic ordering, rounding, time inputs, and random-state ownership where reproducibility requires them.

Use explicit results or exceptions appropriate to the layer. Translate provider and persistence failures at their boundaries rather than exposing SDK-specific errors as core vocabulary.

## Cohesion and Size

As review heuristics, 200–400 lines is often a manageable module, 400–600 warrants scrutiny, and a module over roughly 600 lines normally warrants deliberate decomposition. A folder approaching seven to ten implementation files or mixing several concerns deserves the same consideration.

These numbers are not automatic rejection thresholds. Judge cohesion, public surface, dependency direction, and how much context a reviewer must hold at once.

Prefer a missing value object, policy, focused service, or submodule over a growing chain of unrelated top-level or nested helpers. Small pure helpers remain useful when their responsibility is clear.

## Tests and Tooling

Test domain rules without framework setup. Supply service fakes explicitly through production contracts. Separate domain, orchestration, adapter, and integration checks so feedback remains useful.

Tests should exercise meaningful behavior, invariants, negative paths, and regressions. A difficult-to-replace dependency can expose implicit production wiring; extensive monkeypatching should not become the architectural substitute for injection.

Ruff, mypy, and pytest are the normal Python baseline once configured. Their exact commands, dependencies, and scope belong in the [Lighthouse verification contract](../../development/verification-contract.md). Naming these tools here does not assert that they are installed or that any check has passed.
