---
title: "Offline GitHub Fact Normalization"
created_date: 2026-11-26
update_date: 2026-11-26
status: APPROVED
---

# Offline GitHub Fact Normalization

[`GitHubFacts.normalize`](../../src/lighthouse/adapters/github/facts.py)
maps a supplied, repository-scoped REST `2022-11-28` resource bundle to
[T04 workflow facts](workflow.md). The caller attests collection completeness
and supplies the project profile, accepted work identity (if any), independent
dependency resolution, and captured readiness event binding. The observation
retains its supplied revision and source resource IDs. A populated `hold`
must not be treated as a complete or actionable observation, even when the
mapper can expose an ineligible candidate for inspection.

Readiness requires the current label, latest applicable attributed event,
required task fields and exact captured scope/profile/verification binding.
Scope fingerprints cover title, the full body with LF line endings, and
sorted mapped priority labels. Capturing those fields today does not prove
the authorizing actor saw them. Collecting a complete bound snapshot and
authenticating evidence remain outside this offline mapper.

Only the exact repository/base/accepted work/implementer PR can supply an
effective Lead review or actual Owner merge. A test-merge SHA is not a merge.
Missing result SHA or an unproven pre-merge approval holds. Reviewed head and
merge result remain separate. Execution quiescence and verification receipts
are never inferred from GitHub facts.

This slice has no HTTP transport, key handling, pagination, cache, dispatch,
persistent state change, or CLI entry point. Its fixtures are synthetic and
are not evidence of live provider behavior. Collection/cache is a separate
remaining T06 gate.
