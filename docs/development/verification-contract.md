# Lighthouse Verification Contract

## Current scope

The project currently contains governing documentation, bootstrap instructions,
and adopted architecture/planning documents with conditional integration
candidates. There is no production package,
application test suite, or CI pipeline. This contract describes checks that can
actually run at this stage; it does not approve a future runtime architecture or
dependency-management policy.

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

## Local environment readiness

In an existing project-local virtual environment, verify interpreter and tool
readiness with:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest --version
```

These commands establish environment readiness only. They do not run application
tests or prove package installation reproducibility. Virtual environments and
IDE configuration remain local and are not committed.

## Future Python verification

The [Python guidance](../architecture/standards/Craig-Architecture-Python.md)
names Ruff, mypy, and pytest as the normal baseline once configured. Their
project dependencies, exact lint/type/test commands, and supported Python
versions remain to be established in an approved implementation task.

Do not report Ruff, mypy, or an application test suite as passing before those
checks exist and have actually run. Update this contract and affected local
contracts when that executable verification surface is introduced.
