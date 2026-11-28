# T07 foreground review runner

This is an operator entry for one existing committed REVIEW dispatch. Nothing
is scheduled or selected automatically. A deployed/merged runner is not
permission to run it against a real account or publish a review. The release
profile stays inactive pending independent review and Craig's exact approval.

```powershell
python -m lighthouse review --settings <private-absolute-toml> --dispatch <committed-dispatch-id>
```

The private settings are supplied by the trusted local operator in the
separate review account. Keep the file, actual values, environment references,
private input evidence and checkout paths outside the repository. Set
`version = 1`. Supply only:

- `service`, `profile`, `profile_id`, `ledger`, `cache` and `repository`.
  Name the existing ledger, separate cache, and validated service/project
  TOML files. The slug selects the profile definition, but cannot authorize
  review. Its canonical `lighthouse-profile-v1` fingerprint, captured at
  admission from the validated service switches, numerical actors, workspaces,
  branches, labels, credential reference name and verification definition, must
  equal the existing work binding. TOML formatting is not authority. Profile
  drift or an earlier slug-only binding holds; use normal reconciliation rather
  than migrating an existing reservation. The command does not initialize a ledger.
- `order`, `issue`, `pr`, `head`, `readiness_event` and `verification`.
  All match the accepted binding, original audit and exact committed REVIEW.
  Issue and PR are numeric and the head is a full lowercase SHA.
- `runtime`, `runtime_sha256`, `git`, `codex_home`, `model`, and
  `[environment]`: exact local paths, pinned hash, separately managed runtime
  home and fixed model. Environment contains only the existing allowlist;
  `SystemRoot` and `TEMP` are required. The binding uses a 90-second worker
  cutoff and separate five-second cleanup interval. Keep the publisher
  credential away from Codex and the checkout.
- `intake_ref` and `publisher_ref` are distinct process-environment variable
  names. The trusted operator supplies distinct read-only intake and
  Lead review-publisher capabilities; ordinary tests provide only synthetic
  values. The command never reads a fallback account or starts authentication.
- `evidence_sha256` is the independently captured SHA-256 of the UTF-8 JSON
  object with keys `issue` (body), `pull` (body) and `title` (Issue title),
  ordered lexicographically with no supplemental spaces or ASCII escaping.
  This is a private input, checked against freshly selected normalized evidence;
  unstable or changed scope or review context holds.
- `dependencies` is an array of independently captured resolution rows, each
  with `dependency`, `comment`, `actor`, `revision` (the exact source
  `updated_at`), `body_sha256` (exact comment UTF-8 bytes) and `provenance`.
  Only externally established `unmanaged` provenance can use this comment
  path. A managed or unknown dependency holds; a closed Issue is not proof.

The candidate has exactly one required `## Dependencies` section with
`None` (optionally followed by a period) and no rows, or one line per
captured unmanaged dependency:

```markdown
- owner/repo#123: [resolution](https://github.com/owner/candidate/issues/4#issuecomment-77)
```

Every link is bound to the candidate Issue; fresh GET of each allowlisted
comment verifies author, candidate and dependency identity, update revision,
digest and the resolution fields from the [work intake contract](work-intake.md).
A closed dependency alone, unsupported notation, a missing resolution or
ambiguous duplicate holds. Authoritative reads occur outside ledger writers.

Set the private run's `expected_event` to the separately approved exact event. A different model event holds without publication. The worker's read-only policy is unchanged. Only one explicit JSON outcome
with an event and nonempty review body can reach the separate publisher:
`APPROVE`, `REQUEST_CHANGES`, or `COMMENT`. The expected GitHub receipt is
bound to the exact event, body, PR, commit and numerical Lead identity.
Historical records without an event decode as COMMENT; they cannot be
upgraded. If the POST acknowledgement is missing, a later invocation can look
up only that attempt. It cannot start the model again or issue another POST.
Ambiguous provider output or unconfirmed local cleanup is not approval.

A matched formal review can change the observed workflow disposition. COMMENT
does not approve. Approval alone does not establish a verification receipt
or authorize merge; a missing receipt remains a hold. See the existing
[read-only status and binding limits](runtime-bindings.md).

After independent exact-head review and Craig's merge, propose one controlled
Lighthouse case: exact committed intent, frozen runtime/model, dedicated
account/checkout, approved input/retention policy and separate intake and
publication identities. Select the exact review event and target in advance;
observe attribution, one-shot publication and cleanup. Craig must authorize
that specific operation first. Do not reuse T01 allowances or infer hosted
compatibility, model adherence to structured output, or T07 operational
acceptance from offline tests.
