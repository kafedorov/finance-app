param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$systemPython = (Get-Command python -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $systemPython -m venv .venv
    # Some bundled Python runtimes have pip only in their base environment.
    if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Не удалось создать окружение Python.' }
}
& $venvPython -c 'import fastapi, uvicorn, sqlalchemy, psycopg, argon2, pypdf, httpx' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $systemPython -m pip --python $venvPython install -r backend/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
}
$env:APP_ENV = 'development'
Write-Host "Свод: http://127.0.0.1:$Port"
Write-Host 'Остановить сервер: Ctrl+C'
& $venvPython -m uvicorn backend.asgi:app --host 127.0.0.1 --port $Port --no-access-log
