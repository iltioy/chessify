# Установка окружения chessify на Windows 11.
# Запуск из корня проекта:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Test-Cmd($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

Write-Host "== 1. Системные программы (winget)" -ForegroundColor Cyan
if (-not (Test-Cmd winget)) { throw "winget не найден. Установите 'App Installer' из Microsoft Store." }
$packages = @(
    @{ Cmd = "git";    Id = "Git.Git" },
    @{ Cmd = "node";   Id = "OpenJS.NodeJS.LTS" },
    @{ Cmd = "uv";     Id = "astral-sh.uv" },
    @{ Cmd = "ffmpeg"; Id = "Gyan.FFmpeg" }
)
foreach ($p in $packages) {
    if (Test-Cmd $p.Cmd) { Write-Host "  $($p.Cmd): уже установлен" }
    else {
        Write-Host "  $($p.Cmd): ставлю $($p.Id)"
        winget install --id $p.Id -e --accept-source-agreements --accept-package-agreements
    }
}
Update-SessionPath

Write-Host "== 2. Переменные окружения" -ForegroundColor Cyan
# Кириллица в путях и данных; кэш Hugging Face без симлинков (без режима разработчика Windows).
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
[Environment]::SetEnvironmentVariable("HF_HUB_DISABLE_SYMLINKS_WARNING", "1", "User")
$env:PYTHONUTF8 = "1"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
# Длинные пути (нужны права администратора; без них — предупреждение).
try {
    Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1
    Write-Host "  LongPathsEnabled = 1"
} catch {
    Write-Warning "Не удалось включить длинные пути (нужен запуск от администратора). Держите проект по короткому пути, например C:\chessify."
}

Write-Host "== 3. Python (uv): зависимости, включая GPU (PyTorch cu128)" -ForegroundColor Cyan
uv sync --extra asr --extra diar --group dev

Write-Host "== 4. Шаблон Remotion" -ForegroundColor Cyan
Push-Location render
npm ci
Pop-Location
uv run chessify export-schema
Push-Location render
npm run types
Pop-Location

Write-Host "== 5. Языковые серверы для плагинов Claude Code (pyright-lsp, typescript-lsp)" -ForegroundColor Cyan
npm install -g pyright typescript-language-server typescript

Write-Host "== 6. Ключи" -ForegroundColor Cyan
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "  Создан .env из .env.example. Ключи можно вписать в него или в веб-интерфейсе (Настройки)."
} else { Write-Host "  .env уже есть" }

Write-Host "== Готово. Проверка окружения:" -ForegroundColor Green
uv run chessify doctor
