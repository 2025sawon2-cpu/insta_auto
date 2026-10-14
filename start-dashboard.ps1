$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:Path += ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$dashboardUrl = 'http://127.0.0.1:8775/'
$running = $false
try { $running = (Invoke-WebRequest $dashboardUrl -TimeoutSec 2).StatusCode -eq 200 } catch {}
if (-not $running) {
    $logDir = Join-Path $PSScriptRoot 'data/local-services'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Process -FilePath (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') -ArgumentList @('-X', 'utf8', '-m', 'hotpost', 'serve', '--no-browser', '--host', '127.0.0.1') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'dashboard.out.log') -RedirectStandardError (Join-Path $logDir 'dashboard.err.log')
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $running = (Invoke-WebRequest $dashboardUrl -TimeoutSec 2).StatusCode -eq 200 } catch {}
        if ($running) { break }
    }
    if (-not $running) { throw "Dashboard failed to start. Check $logDir" }
}
Start-Process $dashboardUrl
