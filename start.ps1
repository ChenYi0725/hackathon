$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$candidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    (Join-Path $env:USERPROFILE 'anaconda3\python.exe')
)
$projectPython = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { $projectPython = $candidate; break }
}
if (-not $projectPython) { $projectPython = (Get-Command python -ErrorAction Stop).Source }
& $projectPython -c "import fastapi,uvicorn,pypdf"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Missing dependencies. Run: python -m pip install -r requirements.txt'
    exit 1
}
# The server recognizer can exceed the request budget on local Windows CPUs.
# Keep an explicit caller setting; otherwise use the PP-OCRv5 mobile recognizer.
if (-not $env:OCR_RECOGNITION_MODEL) {
    $env:OCR_RECOGNITION_MODEL = 'PP-OCRv5_mobile_rec'
}
Write-Host "OCR recognition model: $env:OCR_RECOGNITION_MODEL"
Write-Host 'Open http://127.0.0.1:8000 ; Ctrl+C to stop.'
& $projectPython run.py
