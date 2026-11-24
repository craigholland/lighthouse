# Dot Events Assessment Local Contract

## Last Verified (CI)

No CI configured. Local Phase A check evidence belongs to the exact draft PR
head and is not proof of event delivery or worker dispatch.

## Scope

This folder contains the T02 Phase A documentation only. No bridge, fixtures,
runtime, active settings, dependencies or credentials are in scope.

## Purpose

Assess whether the existing Dot coordinator and attached local worker can be
reached by the documented MCP Events and Secure MCP Tunnel candidate. Make
the missing interoperability and authorization evidence explicit.

## Architectural Rules

Keep signal receipt, dispatch identity, a durable experimental claim, worker
acceptance and completion distinct. Treat unknown outcomes as holds, never
as retry authority. No live setup, worker trigger or substituted transport.

## Allowed Dependencies

Markdown and linked first-party documentation only; no new package, build
configuration or credential dependency. Repository coordination from the
isolated existing checkout remains separate from any future T02 runtime.

## Public API / Key Exports

None. The sequence and future fake verification plan are proposals.

## File Index

- [README.md](README.md): assessment, source evidence, proposed bounded proof,
  failure matrix, owner decisions and next Lead gate.

## Known Gaps / Future-State Notes

Custom tunneled Events-to-Dot availability, exact event-triggered local target
binding, durable pre-effect claim enforcement, exact lost-receipt recovery and cost are unresolved. See the report inventory for capability-level evidence. T02 is
not proven and Gate A is open.

## Cross-Folder Contracts

Follow the adopted [architecture](../../docs/architecture/proposal.md) and
[initial plan](../../docs/development/initial-plan.md); this experiment does
not adopt a transport or change either document.

## Verification Contract

Apply the [project verification contract](../../docs/development/verification-contract.md):
existing inert checks plus explicit Markdown file targets. Verify claims and
anchors against official sources. No live T02 action during ordinary checks.
