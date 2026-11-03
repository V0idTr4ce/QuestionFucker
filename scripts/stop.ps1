$ErrorActionPreference = 'SilentlyContinue'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptRoot
$config = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config.json') | ConvertFrom-Json
$appHost = if ($config.app.host) { $config.app.host } else { '127.0.0.1' }
$appPort = if ($config.app.port) { [int]$config.app.port } else { 8765 }
$url = "http://${appHost}:${appPort}/api/shutdown"
Invoke-RestMethod -Method Post -Uri $url -ContentType 'application/json' -Body '{}' -TimeoutSec 5 | Out-Null
Write-Host 'AI搜题服务已停止。若 llama-server 是启动前已存在的实例，它会继续运行。'
