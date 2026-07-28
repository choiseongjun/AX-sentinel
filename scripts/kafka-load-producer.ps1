[CmdletBinding()]
param(
    [ValidateRange(1, 100000)]
    [int]$RatePerSecond = 2000,
    [ValidatePattern("^[a-zA-Z0-9._-]+$")]
    [string]$Topic = "ax.telemetry.events.v1",
    [ValidateRange(0, 86400)]
    [int]$DurationSeconds = 0,
    [ValidateRange(0, 100)]
    [double]$AnomalyPercent = 5,
    [string]$Namespace = "ax-sentinel",
    [string]$KafkaPod = "kafka-0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VirtualEnvironmentPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VirtualEnvironmentPython) {
    $VirtualEnvironmentPython
}
else {
    (Get-Command python -ErrorAction Stop).Source
}

$Arguments = @(
    (Join-Path $PSScriptRoot "kafka-load-producer.py"),
    "--rate", $RatePerSecond,
    "--topic", $Topic,
    "--namespace", $Namespace,
    "--pod", $KafkaPod,
    "--duration-seconds", $DurationSeconds,
    "--anomaly-percent", $AnomalyPercent
)

& $Python @Arguments
exit $LASTEXITCODE
