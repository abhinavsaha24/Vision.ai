param(
    [int]$BackendPort = 8080,
    [int]$FrontendPort = 3001,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"

function Wait-ForTunnelUrl {
    param(
        [string]$LogPath,
        [int]$TimeoutSeconds
    )

    $start = Get-Date
    while (((Get-Date) - $start).TotalSeconds -lt $TimeoutSeconds) {
        if (Test-Path $LogPath) {
            $match = Select-String -Path $LogPath -Pattern "your url is:\s+(https://\S+)" -AllMatches -ErrorAction SilentlyContinue
            if ($match -and $match.Matches.Count -gt 0) {
                return $match.Matches[$match.Matches.Count - 1].Groups[1].Value
            }
        }
        Start-Sleep -Milliseconds 600
    }
    return $null
}

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

$backendOut = Join-Path $runtimeDir "backend.public.out.log"
$backendErr = Join-Path $runtimeDir "backend.public.err.log"
$frontendOut = Join-Path $runtimeDir "frontend.public.out.log"
$frontendErr = Join-Path $runtimeDir "frontend.public.err.log"
$backendTunnelOut = Join-Path $runtimeDir "backend.tunnel.out.log"
$backendTunnelErr = Join-Path $runtimeDir "backend.tunnel.err.log"
$frontendTunnelOut = Join-Path $runtimeDir "frontend.tunnel.out.log"
$frontendTunnelErr = Join-Path $runtimeDir "frontend.tunnel.err.log"

$env:JWT_SECRET = "local-dev-stable-secret-01234567890123456789"
$env:WS_REQUIRE_ORIGIN_HEADER = "false"
$env:WS_ALLOW_QUERY_TOKEN = "false"

$backendListening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
Where-Object { $_.LocalPort -eq $BackendPort }
if (!$backendListening) {
    $backendStartParams = @{
        FilePath               = $pythonExe
        ArgumentList           = @("-m", "uvicorn", "backend.src.api.main:app", "--host", "127.0.0.1", "--port", "$BackendPort")
        WorkingDirectory       = $repoRoot
        RedirectStandardOutput = $backendOut
        RedirectStandardError  = $backendErr
        PassThru               = $true
    }
    $backendProc = Start-Process @backendStartParams
    Set-Content -Path (Join-Path $runtimeDir "backend.public.pid") -Value $backendProc.Id
    Write-Host "Started backend PID $($backendProc.Id)"
}
else {
    Write-Host "Backend already listening on $BackendPort"
}

$backendTunnelParams = @{
    FilePath               = "C:/Program Files/nodejs/npx.cmd"
    ArgumentList           = @("--yes", "localtunnel", "--port", "$BackendPort")
    WorkingDirectory       = $repoRoot
    RedirectStandardOutput = $backendTunnelOut
    RedirectStandardError  = $backendTunnelErr
    PassThru               = $true
}
$backendTunnelProc = Start-Process @backendTunnelParams
Set-Content -Path (Join-Path $runtimeDir "backend.tunnel.pid") -Value $backendTunnelProc.Id

$backendPublicUrl = Wait-ForTunnelUrl -LogPath $backendTunnelOut -TimeoutSeconds $TimeoutSeconds
if (!$backendPublicUrl) {
    throw "Failed to obtain backend tunnel URL. Check $backendTunnelOut"
}
$backendPublicWs = $backendPublicUrl -replace "^https://", "wss://"

$env:NEXT_INTERNAL_API_URL = "http://127.0.0.1:$BackendPort"
$env:NEXT_PUBLIC_WS_URL = $backendPublicWs

$frontendListening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
Where-Object { $_.LocalPort -eq $FrontendPort }
if (!$frontendListening) {
    $frontendStartParams = @{
        FilePath               = "C:/Program Files/nodejs/npm.cmd"
        ArgumentList           = @("run", "dev", "--", "--port", "$FrontendPort")
        WorkingDirectory       = $frontendDir
        RedirectStandardOutput = $frontendOut
        RedirectStandardError  = $frontendErr
        PassThru               = $true
    }
    $frontendProc = Start-Process @frontendStartParams
    Set-Content -Path (Join-Path $runtimeDir "frontend.public.pid") -Value $frontendProc.Id
    Write-Host "Started frontend PID $($frontendProc.Id)"
}
else {
    Write-Host "Frontend already listening on $FrontendPort"
}

$frontendTunnelParams = @{
    FilePath               = "C:/Program Files/nodejs/npx.cmd"
    ArgumentList           = @("--yes", "localtunnel", "--port", "$FrontendPort")
    WorkingDirectory       = $frontendDir
    RedirectStandardOutput = $frontendTunnelOut
    RedirectStandardError  = $frontendTunnelErr
    PassThru               = $true
}
$frontendTunnelProc = Start-Process @frontendTunnelParams
Set-Content -Path (Join-Path $runtimeDir "frontend.tunnel.pid") -Value $frontendTunnelProc.Id

$frontendPublicUrl = Wait-ForTunnelUrl -LogPath $frontendTunnelOut -TimeoutSeconds $TimeoutSeconds
if (!$frontendPublicUrl) {
    throw "Failed to obtain frontend tunnel URL. Check $frontendTunnelOut"
}

Write-Host ""
Write-Host "Public demo mode ready."
Write-Host "Frontend public URL: $frontendPublicUrl"
Write-Host "Backend public URL:  $backendPublicUrl"
Write-Host "Backend WS URL:      $backendPublicWs"
Write-Host ""
Write-Host "Active tunnel + app PIDs saved in $runtimeDir"
Write-Host "Use scripts/stop_demo_sessions.ps1 to close all started processes."
