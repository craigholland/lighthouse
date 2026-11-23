---
title: "Craig Architecture Local Contract Standard"
created_date: 2026-11-21
update_date: 2026-11-21
status: APPROVED
tags: [local-contracts, folder-ownership, ai-guidance, dependency-boundaries, verification-contracts]
---

# Craig Architecture Local Contract Standard

A folder-level `__ai__.md` gives contributors a concise architectural contract near the code or documentation it governs. It supplements [Craig Architecture](Craig-Architecture.md) and the project binding.

## Reconciliation Rule

Updating a contract means reading and reconciling the whole affected section for current truth. Rewrite, move, merge, or remove statements as needed. Completed task history belongs in delivery records; unresolved present limitations belong in Known Gaps.

## Standard Sections

| Section | Content |
| --- | --- |
| Last Verified (CI) | Actual checked commit, time, actor, and check meaning when automated verification exists. Otherwise state the unverified state honestly. |
| Scope | Governed folder and included/excluded patterns. |
| Purpose | Current cohesive responsibility. |
| Architectural Rules | Local invariants and permitted behavior. |
| Allowed Dependencies | Important permitted and forbidden dependencies. |
| Public API / Key Exports | Intended public contracts and relevant symbols. |
| File Index | Selective responsibilities, important consumers, and footguns. |
| Known Gaps / Future-State Notes | Current limitations, accepted simplifications, and unresolved decisions. |
| Cross-Folder Contracts | Concrete assumptions at boundaries. |
| Verification Contract | Commands that are actually runnable and required for this scope. |

## Authoring Shape

Start with the project's required front matter, then use the standard sections:

```text
# <Folder> Local Contract

## Last Verified (CI)
<Actual automated state, or a clear statement that no CI result exists.>

## Scope
<Folder, included patterns, excluded patterns.>

## Purpose
<Current responsibility.>

## Architectural Rules
<Invariants and boundaries.>

## Allowed Dependencies
<Permitted and forbidden dependencies.>

## Public API / Key Exports
<Public names and their meaning.>

## File Index
<Important files, responsibilities, consumers, and footguns.>

## Known Gaps / Future-State Notes
<Unresolved current limitations.>

## Cross-Folder Contracts
<Specific assumptions about other owners.>

## Verification Contract
<Executable commands, working directory, and result interpretation.>
```

## Maintenance and Trust

Keep the contract concise enough to use. Split a broad folder by cohesive concern when one honest contract becomes unwieldy. A parent contract can govern a small tree until narrower ownership becomes useful; empty folders do not require boilerplate.

Update contracts when responsibilities, public APIs, dependency rules, or verification materially change. Review an unchanged contract explicitly when a change remains within its existing meaning.

Verification metadata proves only the declared checks against the identified state. It is not proof of architectural correctness, independent review, or Owner approval. Do not invent a checked SHA or a CI result to fill the template.
