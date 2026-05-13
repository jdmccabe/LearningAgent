param(
    [string]$ModelName = "embeddinggemma:latest"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$modelDir = Join-Path $repoRoot "models\ollama\embeddinggemma"
$modelfile = Join-Path $modelDir "Modelfile"
$modelFile = Join-Path $modelDir "embeddinggemma.gguf"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama CLI was not found on PATH."
}

if (-not (Test-Path -LiteralPath $modelFile)) {
    throw "Missing model file: $modelFile. If this repo was cloned, run 'git lfs pull'."
}

$resolvedModelFile = (Resolve-Path -LiteralPath $modelFile).Path
$tempModelfile = Join-Path $env:TEMP "LearningAgent.embeddinggemma.Modelfile"

@(
    "FROM $resolvedModelFile",
    "TEMPLATE {{ .Prompt }}",
    "PARAMETER num_ctx 2048",
    "PARAMETER num_batch 2048"
) | Set-Content -LiteralPath $tempModelfile -Encoding ASCII

ollama create $ModelName -f $tempModelfile
if ($LASTEXITCODE -ne 0) {
    throw "ollama create failed with exit code $LASTEXITCODE."
}

ollama show $ModelName
if ($LASTEXITCODE -ne 0) {
    throw "ollama show failed with exit code $LASTEXITCODE."
}
