[CmdletBinding()]
param(
    [string]$Endpoint = "http://localhost:8081/api/v1/telemetry",
    [ValidateRange(100, 60000)]
    [int]$IntervalMilliseconds = 1000
)

$ErrorActionPreference = "Continue"

$sensors = @(
    @{
        equipment_id = "PRESS-001"
        sensor_type = "bearing_temperature"
        unit = "C"
        threshold = 90.0
        baseline = 72.0
    },
    @{
        equipment_id = "PRESS-001"
        sensor_type = "vibration_rms"
        unit = "mm/s"
        threshold = 10.0
        baseline = 6.2
    },
    @{
        equipment_id = "MOTOR-002"
        sensor_type = "motor_current"
        unit = "A"
        threshold = 42.0
        baseline = 31.0
    }
)

Write-Output "AX Sentinel telemetry producer started: $Endpoint"

while ($true) {
    $sensor = Get-Random -InputObject $sensors
    $isInjectedAnomaly = (Get-Random -Minimum 1 -Maximum 101) -le 20
    $value = if ($isInjectedAnomaly) {
        $sensor.threshold * (1 + ((Get-Random -Minimum 2 -Maximum 33) / 100))
    }
    else {
        $noiseRatio = (Get-Random -Minimum -60 -Maximum 61) / 1000
        $sensor.baseline * (1 + $noiseRatio)
    }
    $value = [math]::Round($value, 2)
    $isAbnormal = $value -ge $sensor.threshold

    $body = @{
        equipment_id = $sensor.equipment_id
        sensor_type = $sensor.sensor_type
        measured_value = $value
        unit = $sensor.unit
        threshold = $sensor.threshold
        log_excerpt = if ($isAbnormal) {
            "$($sensor.sensor_type) threshold exceeded"
        }
        else {
            "$($sensor.sensor_type) sample received"
        }
    } | ConvertTo-Json -Compress

    try {
        $record = Invoke-RestMethod `
            -Method Post `
            -Uri $Endpoint `
            -ContentType "application/json; charset=utf-8" `
            -Body $body
        Write-Output "$($record.received_at) $($record.equipment_id) $($record.sensor_type)=$($record.measured_value) $($record.status)"
    }
    catch {
        Write-Error "Telemetry delivery failed: $($_.Exception.Message)"
    }

    Start-Sleep -Milliseconds $IntervalMilliseconds
}
