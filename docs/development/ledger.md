---
title: "Offline SQLite Ledger"
created_date: 2026-11-26
update_date: 2026-11-26
status: APPROVED
---

# Offline SQLite Ledger

The inward [ledger port](../../src/lighthouse/application/ledger.py) accepts a
real [T04 decision](workflow.md), its expected prior version, a stable
project-scoped observation/revision key and, when appropriate, one inert
dispatch intent. Callers supply normalized, secret-free evidence. The
[SQLite adapter](../../src/lighthouse/adapters/sqlite/ledger.py) is explicit:
`SQLiteLedger.initialize(path)` initializes a new file; `SQLiteLedger(path)`
opens an existing, recognized file. Neither is wired to the CLI.

Schema v1 keeps one current-state/reservation row per project (an absent work
order is an unreserved slot), uniquely keyed observation audits and globally
unique intent IDs. Explicit write transactions check the expected version and
preserve binding before committing state, audit and intent together. Exact
observation replays are inert, conflicting content is rejected, and stale
versions do not write. A reconciled T04 phase can be saved without recording
another recommendation or intent. Fresh implementation, review and revision
recommendations require a matching new pending intent in the same write.

State, audit and intent queries are views of the same ledger. Pending intent
can be marked uncertain through an explicit correlated write; it cannot be
reset to pending or assigned a replacement identity by the adapter. Reopen
and timeout do not change evidence or release a reservation. These are storage
properties only. There is no dispatcher, external acknowledgment protocol,
retry behavior or multi-ledger coordination.

Do not reset a rejected database. Preserve its file and stop for investigation
of the selected path, schema version or malformed stored evidence. No migration
is provided. Tests use temporary local files and bounded owned Python fixtures;
they do not prove provider delivery, Windows service lifecycle or recovery
from hardware/storage failure.
