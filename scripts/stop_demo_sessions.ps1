$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $repoRoot ".runtime"

function Stop-ByPidFile {
    param([string]$Name)

    $pidFile = Join-Path $runtimeDir $Name
    if (!(Test-Path $pidFile)) {
        Write-Host "Skip $Name (pid file missing)"
        return
    }

    $pidValue = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (!$pidValue) {
        Write-Host "Skip $Name (empty pid)"
        return
    }

    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
    if ($proc) {
        Invoke-CimMethod -InputObject $proc -MethodName Terminate | Out-Null
        Write-Host "Stopped PID $pidValue from $Name"
    }
    else {
        Write-Host "Process $pidValue from $Name already stopped"
    }
}

if (!(Test-Path $runtimeDir)) {
    Write-Host "No runtime directory found at $runtimeDir"
    exit 0
}

Stop-ByPidFile "backend.local.pid"
Stop-ByPidFile "frontend.local.pid"
Stop-ByPidFile "backend.public.pid"
Stop-ByPidFile "frontend.public.pid"
Stop-ByPidFile "backend.tunnel.pid"
Stop-ByPidFile "frontend.tunnel.pid"

Write-Host "Demo session stop routine completed."
