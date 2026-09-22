# Stops any Laplace's Hoard process listening on port 8812.
$ErrorActionPreference = "SilentlyContinue"
$Port = 8812

$Connections = Get-NetTCPConnection -LocalPort $Port -State Listen
if (-not $Connections) {
    Write-Host "Laplace's Hoard does not appear to be running on port $Port."
    exit 0
}

foreach ($conn in $Connections) {
    $processId = $conn.OwningProcess
    Write-Host "Stopping process $processId (port $Port)..."
    Stop-Process -Id $processId -Force
}
Write-Host "Stopped."
