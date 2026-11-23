# Lighthouse Verification Contract

## Current scope

The project contains governing documentation and an installable Python CLI foundation. No orchestration engine, integration, or CI is configured.

Run the following commands from the repository root in PowerShell. A failed
command is a failed check. Record the checked commit and working-tree state in
the PR; describe self-review as self-review.

## Documentation checks

For an uncommitted change, check whitespace with:

```powershell
git diff --check
git diff --cached --check
```

For a committed task branch targeting `development`, check the whole PR change:

```powershell
git diff --check origin/development...HEAD
```

Check local Markdown file targets with this block. It covers the root entry
points and documentation tree, skips external URLs and same-file fragments,
and checks file or directory existence. Heading anchors and link meaning still
require review.

```powershell
$markdownFiles = @('README.md', 'AGENTS.md', '__ai__.md')
$markdownFiles += @(Get-ChildItem -LiteralPath 'docs' -Recurse -File -Filter '*.md' |
    Select-Object -ExpandProperty FullName)
$brokenLinks = @(
    foreach ($file in $markdownFiles) {
        $resolved = (Get-Item -LiteralPath $file).FullName
        $content = Get-Content -Raw -LiteralPath $resolved
        foreach ($match in [regex]::Matches($content, '(?<!!)\[[^\]]+\]\(([^)]+)\)')) {
            $target = ($match.Groups[1].Value -split '#', 2)[0]
            if (-not $target -or $target -match '^[A-Za-z][A-Za-z0-9+.-]*:') {
                continue
            }
            $destination = Join-Path (Split-Path -Parent $resolved) $target
            if (-not (Test-Path -LiteralPath $destination)) {
                '{0}: {1}' -f $file, $target
            }
        }
    }
)
if ($brokenLinks.Count -gt 0) {
    $brokenLinks
    throw 'Broken Markdown file targets.'
}
Write-Output ('Markdown file targets: PASS ({0} documents)' -f $markdownFiles.Count)
```

For standards adoption or later standards updates, compare the complete change
with the approved source and explicitly authorized adaptations. Review each
affected document as a whole to confirm its meaning remains intact. Architecture
and planning documents must preserve the distinction between observed capability,
approved design, unproven candidates and bounded implementation authority.

## Windows Python foundation

Use existing CPython 3.14.x on Windows AMD64. From the repository root, create
a fresh `.venv` with that interpreter (`python -m venv .venv`). Run:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m lighthouse --help
.\.venv\Scripts\python.exe -m lighthouse --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src/lighthouse
```

Use a second, fresh venv created by the same interpreter in a new temporary
directory outside the checkout. Run the same commands from the checkout with
that venv's absolute Python path. Compare the two `python -m pip list
--format=freeze` outputs by package and version; they must match. Also use the
second venv from outside the repository root to run both `python -m lighthouse
--help` and `python -m lighthouse --version`, without changing `PYTHONPATH`.
Verify an invalid argument exits nonzero. Tests exercise these installed CLI
paths and guard against integration side effects.

Record the exact checks and exit statuses, interpreter and tool versions,
checked commit and tree state, and current review head in the PR. This is local
verification, not CI or evidence of a live integration.

### Regenerate the development lock deliberately

In a clean scratch venv on the supported target, use the pip version pinned in
the current lock (or review an intentional change to that pin). Resolve the
build requirements and development extras listed in `pyproject.toml`, including
their dependencies, against a trusted package index. Do not install Lighthouse
in this resolver venv. Capture `python -m pip list --format=freeze`, review
the resulting versions including pip and transitive dependencies, and update
`requirements-dev.lock` with exact pins only. Update the declared direct
requirements if their pins change. Never include local paths, credential-bearing
index URLs, or editable entries. Validate by repeating the two fresh installs
and checks above. This establishes version repeatability on the documented
target, not a byte-identical or offline build guarantee.
