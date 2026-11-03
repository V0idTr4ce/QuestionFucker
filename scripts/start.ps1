param(
    [switch]$NoBrowser,
    [string]$OpenTarget = ''
)
$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptRoot
$config = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config.json') | ConvertFrom-Json

function Resolve-ConfigPath([string]$Value) {
    if (-not $Value) { return $null }
    $expanded = [Environment]::ExpandEnvironmentVariables($Value)
    if ([IO.Path]::IsPathRooted($expanded)) { return [IO.Path]::GetFullPath($expanded) }
    return [IO.Path]::GetFullPath((Join-Path $root $expanded))
}

$appHost = if ($config.app.host) { $config.app.host } else { '127.0.0.1' }
$appPort = if ($config.app.port) { [int]$config.app.port } else { 8765 }
$url = "http://${appHost}:${appPort}"

# 默认打开配置指定的小窗页面；-NoBrowser 时只启动后台。
if (-not $NoBrowser -and -not $OpenTarget) {
    $page = Resolve-ConfigPath ([string]$config.app.page_path)
    if ($page -and (Test-Path -LiteralPath $page -PathType Leaf)) { $OpenTarget = $page }
}

# 主题库有更新时，按 config.json 指定位置同步。
$mainBank = Resolve-ConfigPath ([string]$config.question_bank.sync_from)
$localBank = Resolve-ConfigPath ([string]$config.question_bank.path)
if ($mainBank -and $localBank -and (Test-Path -LiteralPath $mainBank)) {
    $localDir = Split-Path -Parent $localBank
    if (-not (Test-Path -LiteralPath $localDir)) { New-Item -ItemType Directory -Path $localDir -Force | Out-Null }
    $needCopy = -not (Test-Path -LiteralPath $localBank)
    if (-not $needCopy) {
        $src = Get-Item -LiteralPath $mainBank
        $dst = Get-Item -LiteralPath $localBank
        $needCopy = ($src.Length -ne $dst.Length) -or ($src.LastWriteTimeUtc -gt $dst.LastWriteTimeUtc)
    }
    if ($needCopy) { Copy-Item -LiteralPath $mainBank -Destination $localBank -Force }
}

try {
    $existing = Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 2
    if ($existing.phase -ne 'error') {
        if ($OpenTarget) { Start-Process $OpenTarget }
        elseif (-not $NoBrowser) { Start-Process $url }
        exit 0
    }
    Invoke-RestMethod -Method Post -Uri "$url/api/shutdown" -ContentType 'application/json' -Body '{}' -TimeoutSec 3 | Out-Null
    Start-Sleep -Seconds 1
} catch {}

$python = $null
$configuredPython = Resolve-ConfigPath ([string]$config.app.python_executable)
if ($configuredPython) {
    if (-not (Test-Path -LiteralPath $configuredPython)) { throw "config.json 中的 app.python_executable 不存在：$configuredPython" }
    $python = $configuredPython
} else {
    foreach ($name in @('python.exe', 'python', 'py.exe', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $python = $cmd.Source; break }
    }
}
if (-not $python) { throw '未找到 Python 3；请在 config.json 的 app.python_executable 中填写完整路径。' }

$stdout = Join-Path $root 'logs\app.stdout.log'
$stderr = Join-Path $root 'logs\app.stderr.log'
$logs = Join-Path $root 'logs'
if (-not (Test-Path -LiteralPath $logs)) { New-Item -ItemType Directory -Path $logs -Force | Out-Null }
$args = @('-u', (Join-Path $scriptRoot 'app.py'))
if ([IO.Path]::GetFileName($python) -in @('py.exe', 'py')) { $args = @('-3') + $args }

Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $scriptRoot `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden

$started = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $null = Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 1
        $started = $true
        break
    } catch {}
}
if (-not $started) {
    if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr }
    throw 'AI搜题服务启动失败，请查看 logs\app.stderr.log。'
}
if ($OpenTarget) { Start-Process $OpenTarget }
elseif (-not $NoBrowser) { Start-Process $url }
