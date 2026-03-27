Param(
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

$targets = @(
    "__pycache__",
    ".pytest_cache",
    ".next_local",
    ".runtime"
)

$removed = @()

foreach ($name in $targets) {
    $matches = Get-ChildItem -Path $repoRoot -Recurse -Force -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq $name -and $_.FullName -notmatch "\\.venv\\|\\node_modules\\" }

    foreach ($m in $matches) {
        if ($DryRun) {
            Write-Host "[DRY-RUN] Would remove: $($m.FullName)"
            continue
        }
        Remove-Item -Path $m.FullName -Recurse -Force -ErrorAction SilentlyContinue
        $removed += $m.FullName
        Write-Host "Removed: $($m.FullName)"
    }
}

if ($DryRun) {
    Write-Host "Dry run complete."
}
else {
    Write-Host "Cleanup complete. Removed $($removed.Count) directories."
}