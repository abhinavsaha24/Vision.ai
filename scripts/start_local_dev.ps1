param(
    [int]$BackendPort = 8080,
    [int]$FrontendPort = 3001
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv/Scripts/python.exe"
$frontendDir = Join-Path $repoRoot "frontend"
$runtimeDir = Join-Path $repoRoot ".runtime"

if (!(Test-Path $pythonExe)) {
    throw "Python venv not found at $pythonExe"
}

if (!(Test-Path $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
}

$backendOut = Join-Path $runtimeDir "backend.local.out.log"
$backendErr = Join-Path $runtimeDir "backend.local.err.log"
$frontendOut = Join-Path $runtimeDir "frontend.local.out.log"
$frontendErr = Join-Path $runtimeDir "frontend.local.err.log"

$backendListening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
Where-Object { $_.LocalPort -eq $BackendPort }
$frontendListening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
Where-Object { $_.LocalPort -eq $FrontendPort }

if (!$backendListening) {
    $env:JWT_SECRET = "local-dev-stable-secret-01234567890123456789"
    $env:WS_REQUIRE_ORIGIN_HEADER = "false"
    $env:WS_ALLOW_QUERY_TOKEN = "false"

    $backendStartParams = @{
        FilePath               = $pythonExe
        ArgumentList           = @("-m", "uvicorn", "backend.src.api.main:app", "--host", "127.0.0.1", "--port", "$BackendPort")
        WorkingDirectory       = $repoRoot
        RedirectStandardOutput = $backendOut
        RedirectStandardError  = $backendErr
        PassThru               = $true
    }
    $backendProc = Start-Process @backendStartParams

    Set-Content -Path (Join-Path $runtimeDir "backend.local.pid") -Value $backendProc.Id
    Write-Host "Started backend PID $($backendProc.Id) on http://127.0.0.1:$BackendPort"
}
else {
    Write-Host "Backend already listening on port $BackendPort"
}

if (!$frontendListening) {
    $env:NEXT_INTERNAL_API_URL = "http://127.0.0.1:$BackendPort"
    $env:NEXT_PUBLIC_WS_URL = "ws://127.0.0.1:$BackendPort"

    $frontendStartParams = @{
        FilePath               = "C:/Program Files/nodejs/npm.cmd"
        ArgumentList           = @("run", "dev", "--", "--port", "$FrontendPort")
        WorkingDirectory       = $frontendDir
        RedirectStandardOutput = $frontendOut
        RedirectStandardError  = $frontendErr
        PassThru               = $true
    }
    $frontendProc = Start-Process @frontendStartParams

    Set-Content -Path (Join-Path $runtimeDir "frontend.local.pid") -Value $frontendProc.Id
    Write-Host "Started frontend PID $($frontendProc.Id) on http://127.0.0.1:$FrontendPort"
}
else {
    Write-Host "Frontend already listening on port $FrontendPort"
}

Write-Host "Local mode ready."
Write-Host "Backend:  http://127.0.0.1:$BackendPort/health"
Write-Host "Frontend: http://127.0.0.1:$FrontendPort/dashboard"
Write-Host "Logs in:  $runtimeDir"
