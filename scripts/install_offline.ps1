param(
    [string]$Wheelhouse = "vendor\wheels",
    [string]$Requirements = "vendor\requirements-runtime.txt"
)

$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path $Wheelhouse)) {
    throw "Offline wheelhouse not found: $Wheelhouse"
}

python -m pip install --no-index --find-links $Wheelhouse --requirement $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "offline dependency installation failed with exit code $LASTEXITCODE"
}
python -m pip install --no-build-isolation --no-deps --editable .
if ($LASTEXITCODE -ne 0) {
    throw "LearningAgent registration failed with exit code $LASTEXITCODE"
}

Write-Host "LearningAgent offline install complete."
