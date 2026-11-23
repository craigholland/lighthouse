---
title: "Craig Architecture"
created_date: 2026-11-21
update_date: 2026-11-22
status: APPROVED
tags: [craig-architecture, clean-architecture, solid, domain-modeling, dependency-injection, deterministic-state]
---

# Craig Architecture

Craig Architecture is an applied architectural philosophy for building maintainable systems through small, understandable increments. It gives human and AI contributors a shared direction while allowing a young system to discover its useful structure.

> Build intentionally dirty in a clean way.

Exploratory code may have provisional responsibility placement. It should preserve a clear route to refactoring. Stable rules belong in a core that remains understandable as interfaces, storage, frameworks, and providers evolve.

## Dependency Invariant

Inner layers must not depend on outer implementation details. This remains true during exploration.

- Domain rules do not import presentation, database, transport, provider SDK, or application-startup code.
- Application services depend on inward-owned contracts for external capabilities.
- Outer adapters translate external representations and implement those contracts.
- Composition at an outer entry point selects implementations and passes dependencies explicitly.

Temporary co-location of simple exploratory structures may be inexpensive to undo. Embedding stable reasoning in framework objects, hidden global lookup, or vendor-specific payloads makes later cleanup harder.

## Responsibilities and Boundaries

| Concern | Owns | Boundary |
| --- | --- | --- |
| Interface / delivery | Input handling, delivery validation, and translation of requests/results. | Calls application behavior; does not define stable domain outcomes. |
| Application / services | Use-case sequencing, transactions, and coordination of domain behavior and external capabilities. | Keeps stable policies in the domain and concrete adapters outside. |
| Domain | Entities, value objects, invariants, state transitions, and deterministic policies. | Can be understood and tested without a framework, database, or network. |
| Ports / contracts | Capabilities required by the consuming inner layer. | Express system vocabulary, not a mirror of a provider SDK. |
| Infrastructure / adapters | Persistence, filesystems, provider integrations, serialization mappings, and operational mechanics. | Translate at the boundary and preserve domain ownership. |

These are responsibility boundaries, not mandatory package names or separate processes. A small system need not create every layer as its own package. Runtime calls through an injected port do not reverse the source dependency rule.

## Explore and Exploit

Treat maturity as architectural judgment rather than a numeric score.

An exploratory concept should have a small dependency surface and remain easy to rename, relocate, split, or discard. Avoid abstractions whose users and invariants are still unknown.

When a concept becomes stable enough to build upon, clarify its naming, move stable reasoning to its proper owner, tighten its public contract, and strengthen its tests. Do not leave a widely depended-on concept indefinitely labeled temporary.

The direction of development is deliberate: explore lightly, identify stable concepts, give them clear ownership, and use those contracts as the foundation for further work.

## Canonical State and Derived Projections

Identify the authoritative state for each concept. Views, caches, summaries, indexes, and other projections derive from that state and should be rebuildable where practical.

Rendering, persistence layout, and provider payloads must not quietly become competing definitions of domain truth. Translate at boundaries and make deliberate transformations visible.

## Explicit Dependency Wiring

Prefer constructor parameters, function parameters, or small composition functions at startup and other outer entry points. Tests can supply fakes through the same boundaries.

Manual wiring is a useful starting point. A dependency-injection container earns its place when repeated wiring, object lifetimes, or environment-dependent composition becomes difficult to manage. Its APIs remain outside the core.

Avoid inner-layer service locators, global registries, and framework annotations that conceal required dependencies. Repetition at a small composition boundary is easier to repair than hidden dependency direction.

## Determinism and Observable State Changes

Prefer explicit state transitions with reproducible inputs and outputs. Supply time, random state, and external observations through defined boundaries when they affect the result.

Make units, rounding, ordering, and failure behavior explicit where they matter. Determinism supports diagnosis, replay, simulation, and meaningful automated tests; it does not imply that every external physical or provider event is deterministic.

## Code Shape and Evolution

Physical organization is an architectural choice. Make it easy for a person or an AI contributor to find a concept, identify its owner, recognize its public contract, and locate relevant tests. Organize by responsibility first, then by subject where that adds clarity. Consistent names and local contracts make the same concept traceable across layers without making their types interchangeable or requiring every repository to use the same tree.

Keep modules cohesive and files reviewable. A large service, broad folder, or brittle helper chain is a prompt to identify a missing object, policy, contract, or bounded module.

Keep public surfaces small. Components communicate through intended contracts rather than reaching into each other's private state. Reuse and extend an existing owner before creating a parallel implementation.

Favor clarity and the smallest meaningful product increment. Separate process deployment, broad frameworks, elaborate infrastructure, and general-purpose abstraction require a concrete need.

## Applying the Philosophy

Use [planning and decomposition](Craig-Architecture-Planning-And-Decomposition.md) to shape work, [Python guidance](Craig-Architecture-Python.md) for Python implementation, [AI contributor guidance](AI_Guidance/Craig-Architecture-AI-Guidance.md) for agent execution, and the [local contract standard](Craig-Architecture-__ai__-Template.md) for nearby architectural context.

Passing tools supports judgment. Architectural correctness still requires checking responsibility placement, dependency direction, real composition, and agreement with the authoritative requirements.
