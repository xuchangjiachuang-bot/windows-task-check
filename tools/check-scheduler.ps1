param(
    [Parameter(Mandatory)][string]$Python,
    [string]$OutputDirectory = ''
)
# Opt-in: registers one uniquely named, limited, interactive task, runs it once,
# and removes only that task in finally. No triggers, credentials or elevation.
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot '../runtime/scheduler' }
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$pythonw = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe is required beside Python.' }
$probe = (& $pythonPath -I -c "import pathlib,wintaskcheck; print(pathlib.Path(wintaskcheck.__file__).with_name('_probe.py'))")
if ($LASTEXITCODE -ne 0) { throw 'Install windows-task-check in the supplied interpreter first.' }
$null = New-Item -ItemType Directory -Force -Path $OutputDirectory
$root = (Resolve-Path -LiteralPath $OutputDirectory).Path
$runDirectory = Join-Path $root ([guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $runDirectory
$taskName = 'WindowsTaskCheck-' + [guid]::NewGuid().ToString('N')
$registered = $false
$summary = [ordered]@{task_name=$taskName; passed=$false; task_removed=$false; last_task_result=$null; error=$null}
try {
    # File paths cannot contain quote characters; all interpolated paths are quoted.
    $arguments = '-m wintaskcheck run --timeout 30 --output-dir "' + $runDirectory + '" -- "' + $pythonPath + '" "' + $probe + '" report 37 scheduled'
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $runDirectory
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $null = Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings
    $registered = $true
    $before = (Get-Date).AddSeconds(-2)
    Start-ScheduledTask -TaskName $taskName
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 200
        $task = Get-ScheduledTask -TaskName $taskName
        $info = Get-ScheduledTaskInfo -TaskName $taskName
        if ($info.LastRunTime -gt $before -and $task.State -ne 'Running' -and $task.State -ne 'Queued') { break }
    } while ((Get-Date) -lt $deadline)
    $summary.last_task_result = $info.LastTaskResult
    $receiptFile = Get-ChildItem -LiteralPath $runDirectory -Filter result.json -Recurse | Select-Object -First 1
    if (-not $receiptFile) { throw 'No execution receipt was written.' }
    $receipt = Get-Content -LiteralPath $receiptFile.FullName -Raw | ConvertFrom-Json
    $observation = Get-Content -LiteralPath $receipt.stdout -Raw | ConvertFrom-Json
    $summary.passed = ($info.LastTaskResult -eq 37 -and $receipt.state -eq 'completed' -and $receipt.exit_code -eq 37 -and $observation.console_handle -eq 0)
} catch {
    $summary.error = $_.Exception.GetType().FullName
} finally {
    if ($registered) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        $summary.task_removed = ($null -eq (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue))
    }
    $summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDirectory 'scheduler-check.json') -Encoding UTF8
}
$summary | ConvertTo-Json -Compress
if (-not $summary.passed -or -not $summary.task_removed) { exit 1 }
