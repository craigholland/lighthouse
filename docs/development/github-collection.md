---
title: "Offline GitHub Collection and Cache"
created_date: 2026-11-26
update_date: 2026-11-26
status: APPROVED
---

# Offline GitHub Collection and Cache

Use [`GitHubCollector.collect`](../../src/lighthouse/adapters/github/collection.py)
for one serial scan. Supply a validated project, its Lead read identity, per-Issue
contexts, observation revision, time, and finite budget (default 20). A scan
discovers ready Issues and also reconciles explicitly accepted work, including
closed resources and an independently linked PR. It refreshes the full Issue
and PR records without validators before returning observations. A failed scan
returns no observations. Any individual [mapper](github-facts.md) hold remains
non-actionable; the collector never changes T05 state or releases a reservation.

The explicit disposable [cache](../../src/lighthouse/adapters/github/cache.py)
stores each body with validator and Link in one SQLite write, keyed by repository,
read identity, canonical URL/query, API version and media type. No token is
stored. A matching 304 can use a validated prior representation, including its
next page, but never substitutes for the final refresh. Rate limits return a
retry time when provided; callers decide when to try again. Partial scans may
leave reusable response pages but never save authority or a successful scan.

The dormant [HTTPS adapter](../../src/lighthouse/adapters/github/transport.py)
sends only scoped GETs with a privately injected token, uses bounded socket
timeouts, and never follows redirects. Numeric pagination aliases require a
matching repository identity read and are translated to the named route.
No credential loader, polling loop, dispatch, publication or launch is wired.
Readiness bindings, dependency resolutions, execution observations and test
receipts remain independent caller inputs; a cache hit proves none of them.

Tests use injected fake HTTP, temporary SQLite and a short owned fresh Python
process. They do not prove live GitHub compatibility, configured permissions,
or cross-resource atomic snapshots. No live integration is authorized here.
