$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# 由 install-watchdog-task.ps1 的排程每 5 分鐘執行：後端在跑、Webhook 閘道（ngrok 或 cloudflared）卻不見時，只重啟閘道。
# 不啟動或重啟後端：後端停止代表操作人刻意停機或正在部署，而且重啟後端可能帶上尚未部署的程式。
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'runtime-common.ps1')
$runtime = Join-Path $projectRoot '.runtime'
[void](New-Item -ItemType Directory -Force -Path $runtime)
$log = Join-Path $runtime 'watchdog.log'

function Write-WatchdogLog {
    param([string]$Message)
    Add-Content -LiteralPath $log -Value ("{0} {1}" -f [DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'), $Message) -Encoding UTF8
    # 只留最近 500 行，避免每 5 分鐘一次的紀錄無限成長。
    $lines = @(Get-Content -LiteralPath $log -Encoding UTF8)
    if ($lines.Count -gt 600) { Set-Content -LiteralPath $log -Value ($lines | Select-Object -Last 500) -Encoding UTF8 }
}

# 與 start-all.ps1 同一把鎖：一鍵啟動或部署進行中時不插手。
$digest = [System.Security.Cryptography.SHA256]::Create()
$rootHash = [BitConverter]::ToString($digest.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot))).Replace('-', '').Substring(0, 16)
$digest.Dispose()
$mutex = [Threading.Mutex]::new($false, "Local\MwbStart-$rootHash")
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { exit 0 }
    if (-not (Get-MwbProcess -Name backend -Root $projectRoot)) { exit 0 }
    if (Get-MwbProcess -Name gateway -Root $projectRoot) { exit 0 }
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    Push-Location $projectRoot
    try {
        $port = & $node --input-type=module -e "import {readSettings,backendPort} from './scripts/webhooks.mjs'; console.log(backendPort(readSettings()))"
        if ($LASTEXITCODE -ne 0) { throw '後端連接埠設定不合法（BACKEND_INTERNAL_URL／APP_ORIGIN）。' }
        $gatewaySeconds = & $node --input-type=module -e "import {readSettings,gatewayStartupSeconds} from './scripts/webhooks.mjs'; console.log(gatewayStartupSeconds(readSettings()))"
        if ($LASTEXITCODE -ne 0) { throw 'Webhook 閘道等待時間設定不合法。' }
    } finally { Pop-Location }
    try { $healthy = (Invoke-WebRequest -Uri "http://127.0.0.1:$([int]$port)/api/health" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { $healthy = $false }
    if (-not $healthy) { Write-WatchdogLog '閘道不在執行，但後端健康檢查未通過；不重啟閘道，請檢查後端。'; exit 0 }
    # 重啟會覆寫閘道日誌；先把上一次結束前的最後幾行留下來，事後才查得到原因。
    foreach ($name in 'gateway.stderr.log', 'gateway.stdout.log') {
        $path = Join-Path $runtime $name
        if (Test-Path -LiteralPath $path) {
            $tail = @(Get-Content -LiteralPath $path -Encoding UTF8 -Tail 3) -join ' | '
            Write-WatchdogLog "上次 $name 最後幾行：$(if ($tail) { $tail } else { '（空白）' })"
        }
    }
    Write-WatchdogLog '偵測到 Webhook 閘道不在執行，重新啟動。'
    Assert-MwbPortFree -Port ([int](Get-MwbGatewayAgent -Root $projectRoot -Node $node).port)
    Start-MwbGateway -Root $projectRoot -Node $node -Seconds ([int]$gatewaySeconds)
    # 與 start-all 相同的公開邊界關卡；不通過就停掉剛啟動的閘道，下一輪再試。
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $projectRoot
    try { $output = @(& $node scripts/webhooks.mjs check 2>&1 | ForEach-Object { "$_" }); $code = $LASTEXITCODE }
    finally { Pop-Location; $ErrorActionPreference = $previousPreference }
    if ($code -ne 0) {
        Stop-MwbProcess -Name gateway -Root $projectRoot
        throw "Webhook 公開邊界驗證未通過，已停止閘道：$(($output | Select-Object -Last 1))"
    }
    Write-WatchdogLog '閘道已重新啟動，固定網址與公開邊界驗證通過。'
} catch {
    Write-WatchdogLog "重啟失敗：$($_.Exception.Message)"
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
