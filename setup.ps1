param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Invoke-Checked $Python @("-m", "venv", ".venv")
}
$ProjectPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Invoke-Checked $ProjectPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked $ProjectPython @("-m", "pip", "install", "torch==2.6.0", "torchaudio==2.6.0", "--index-url", "https://download.pytorch.org/whl/cu124")
Invoke-Checked $ProjectPython @("-m", "pip", "install", "-r", "requirements.txt")
Invoke-Checked $ProjectPython @("pipeline.py", "--check")
Write-Host "Setup complete. Open run.bat to start."
