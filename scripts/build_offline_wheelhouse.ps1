param(
    [string]$Wheelhouse = "vendor\wheels",
    [string]$Requirements = "vendor\requirements-runtime.txt"
)

$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null

Write-Host "Building offline wheelhouse in $Wheelhouse"
python -m pip wheel --wheel-dir $Wheelhouse --requirement $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "pip wheel failed with exit code $LASTEXITCODE"
}

Write-Host "Verifying wheelhouse can satisfy runtime requirements without an index"
python -m pip install --dry-run --ignore-installed --no-index --find-links $Wheelhouse --requirement $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "offline wheelhouse verification failed with exit code $LASTEXITCODE"
}

Write-Host "Offline wheelhouse is ready."
