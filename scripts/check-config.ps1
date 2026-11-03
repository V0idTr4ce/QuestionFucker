$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptRoot
$configPath = Join-Path $root 'config.json'
$checkerPath = Join-Path $scriptRoot 'check_config.py'

if (-not (Test-Path -LiteralPath $configPath)) { throw "缺少配置文件：$configPath" }
if (-not (Test-Path -LiteralPath $checkerPath)) { throw "缺少检查程序：$checkerPath" }

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$configuredPython = [string]$config.app.python_executable
$pythonCommand = $null
$pythonArgs = @()

if ($configuredPython) {
    if (-not [IO.Path]::IsPathRooted($configuredPython)) {
        $configuredPython = Join-Path $root $configuredPython
    }
    if (-not (Test-Path -LiteralPath $configuredPython -PathType Leaf)) {
        throw "config.json 中的 app.python_executable 不存在：$configuredPython"
    }
    $pythonCommand = $configuredPython
} elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    $pythonCommand = (Get-Command python.exe).Source
} elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $pythonCommand = (Get-Command py.exe).Source
    $pythonArgs = @('-3')
} else {
    throw '未找到 Python 3。请安装 Python，或在 config.json 的 app.python_executable 中填写完整路径。'
}

$env:PYTHONIOENCODING = 'utf-8'
& $pythonCommand @pythonArgs $checkerPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
