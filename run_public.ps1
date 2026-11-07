# Puts Food Match online from this PC through a free Cloudflare quick tunnel.
#
#   Right-click > Run with PowerShell, or from the project folder:
#   powershell -ExecutionPolicy Bypass -File run_public.ps1
#
# It prints an https://....trycloudflare.com link anyone can open. The link
# changes every time this script starts. Keep this window open (and the PC
# awake) while people use it; press Ctrl+C to take the site offline.
#
# Uses the local PostgreSQL database and the venv. Debug mode is off and the
# app only listens on 127.0.0.1, so the tunnel is the only way in.
$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
$python = Join-Path $project "venv\Scripts\python.exe"
$cloudflared = Join-Path $env:LOCALAPPDATA "cloudflared\cloudflared.exe"
if (-not (Test-Path $python)) { throw "Python venv not found at $python" }
if (-not (Test-Path $cloudflared)) { throw "cloudflared not found at $cloudflared" }

# Public settings for this run only (.env is not changed).
$env:DEBUG = "False"
$env:ALLOWED_HOSTS = "localhost,127.0.0.1,.trycloudflare.com"
$env:CSRF_TRUSTED_ORIGINS = "https://*.trycloudflare.com"
$env:TRUST_CF_CONNECTING_IP = "True"
$env:HTTPS_ENABLED = "False"   # Cloudflare already provides HTTPS
$env:PYTHONUTF8 = "1"

$tunnelLog = Join-Path $env:TEMP "foodmatch-tunnel.log"
if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }

Write-Host "Starting Food Match on http://127.0.0.1:8000 ..."
$server = Start-Process -FilePath $python -WorkingDirectory $project -NoNewWindow -PassThru `
    -ArgumentList "manage.py", "runserver", "127.0.0.1:8000", "--insecure", "--noreload"

Write-Host "Opening the Cloudflare tunnel ..."
$tunnel = Start-Process -FilePath $cloudflared -NoNewWindow -PassThru -RedirectStandardError $tunnelLog `
    -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8000"

try {
    $url = $null
    for ($i = 0; $i -lt 60 -and -not $url; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $tunnelLog) {
            $hit = Select-String -Path $tunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { $url = $hit.Matches[0].Value }
        }
    }
    if ($url) {
        Write-Host ""
        Write-Host "Food Match is online at:  $url" -ForegroundColor Green
        Write-Host "Share this link. Press Ctrl+C here to take it offline."
        Write-Host ""
    } else {
        Write-Host "The tunnel did not report a link yet; see $tunnelLog" -ForegroundColor Yellow
    }
    Wait-Process -Id $server.Id
} finally {
    foreach ($p in @($tunnel, $server)) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "Food Match is offline."
}
