$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile = Join-Path $scriptPath "server_restart.log"
$serverScript = Join-Path $scriptPath "run_web.py"

Set-Location $scriptPath

function Write-Log {
    param([string]$msg)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $msg" | Out-File -FilePath $logFile -Encoding UTF8 -Append
    Write-Host "$timestamp $msg"
}

Write-Log "=== Server Monitor Started ==="

while ($true) {
    $proc = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { 
        try { $_.CommandLine -match "run_web" } catch { $false }
    }
    if (-not $proc) {
        Write-Log "Server not running, starting..."
        try {
            Start-Process python -ArgumentList "run_web.py" -WorkingDirectory $scriptPath -NoNewWindow
            Write-Log "Server started successfully"
        } catch {
            Write-Log "Failed to start server: $_"
        }
    }
    Start-Sleep -Seconds 30
}
