---
title: "Lighthouse Offline Configuration"
created_date: 2026-11-26
update_date: 2026-11-26
status: APPROVED
---

# Offline configuration, version 1

Call `lighthouse.configuration.load_configuration(service_path, project_paths)`
with explicit path objects. It reads only those TOML files and returns immutable
typed settings and profiles in input order. It never opens workspaces, resolves
credential references, contacts a provider, or runs verification commands.

- [Shared service](../../config/examples/service.toml): `version = 1` is required.
  The only supported safety settings are `max_active_work = 1`,
  `independent_review = true` and `human_merge = true`, also their defaults.
- [Alpha](../../profiles/examples/alpha.toml) and [Beta](../../profiles/examples/beta.toml)
  show the project fields: version, project slug, repository, source-control
  adapter identifier (`github` in v1), `credential_ref`, distinct numeric
  `actors`, separate `workspaces` and required `verification`.
  `active` defaults to false and cannot be true. No profile enables execution.
- Optional `branches` defaults to development/main. Optional `labels` maps ready,
  blocked, high, normal and low to the default names in the
  [intake contract](work-intake.md). Duplicate mapped labels are rejected.
- Workspaces are drive-absolute Windows paths; slash, case and dot segments are
  compared lexically. Equal and nested paths are rejected across registrations.
  There is no filesystem identity, symlink or junction verification in this slice.
  Repositories are unique case-insensitively; project slugs are unique.
- Verification requires a repository-relative `directory` and nonempty string
  `commands` list. Commands are data, never execution authority here. Secret
  references are opaque `ref:` aliases, not secret values.
- Unknown fields, invalid TOML, unsupported policy/version and invalid values
  raise `ConfigurationError` with fixed labels, not raw values or paths.
  Both examples are synthetic. Keep private profiles and bindings out of Git.

Use the [Issue template](../../.github/ISSUE_TEMPLATE/implementation.md) and
[PR template](../../.github/PULL_REQUEST_TEMPLATE.md) for work intake. Neither
grants readiness; see the intake contract for the bootstrap work-order exception.

The [T07 review runner](review-runner.md) explicitly composes one private
per-run packet with these validated inactive definitions. None of the public
profile examples is an operational packet or authorizes provider access.

At an admission boundary capture `profile_fingerprint(service, profile)` in
the accepted binding. The versioned canonical representation hashes normalized
policy data, not the syntactic TOML, private credential values or its filename.
A profile slug names a definition; it does not attest its contents.
