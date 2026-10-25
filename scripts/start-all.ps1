param([switch]$Restart, [switch]$InstallDependencies, [switch]$SuppressSystemAlerts, [switch]$ApplyMigrations)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'runtime-common.ps1')
$runtime = Join-Path $projectRoot '.runtime'
[void](New-Item -ItemType Directory -Force -Path $runtime)
$digest = [System.Security.Cryptography.SHA256]::Create()
$rootHash = [BitConverter]::ToString($digest.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot))).Replace('-', '').Substring(0, 16)
$digest.Dispose()
$mutex = [Threading.Mutex]::new($false, "Local\MwbStart-$rootHash")
$locked = $false
$started = [System.Collections.Generic.List[string]]::new()

function Invoke-Step {
    param([string]$Executable, [string[]]$Arguments, [string]$Directory, [string]$Label)
    Write-Host $Label
    Push-Location $Directory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$Label 失敗（exit $LASTEXITCODE）。" }
    } finally { Pop-Location }
}

function Invoke-StepWithRetry {
    param([string]$Executable, [string[]]$Arguments, [string]$Directory, [string]$Label, [int]$Seconds = 120)
    # 登入後自動啟動時網路與 Tailscale 常常還沒就緒；先重試一段時間再判定失敗。
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ($true) {
        try { Invoke-Step $Executable $Arguments $Directory $Label; return $true }
        catch {
            if ([DateTime]::UtcNow.AddSeconds(10) -gt $deadline) { Write-Host $_.Exception.Message; return $false }
            Write-Host "$Label 尚未通過；10 秒後重試（最多等待 $Seconds 秒）。"
            Start-Sleep -Seconds 10
        }
    }
}

function Get-MwbMigrationState {
    param([string]$Python, [string]$Backend)
    # 只讀版本：alembic 的 INFO 日誌寫在 stderr，不轉向（PS 5.1 轉向 stderr 會在 Stop 模式下變成例外），只收 stdout。
    Push-Location $Backend
    try {
        $heads = @(& $Python -m alembic heads)
        if ($LASTEXITCODE -ne 0) { throw '無法讀取程式的 migration 版本（alembic heads）。' }
        $current = @(& $Python -m alembic current)
        if ($LASTEXITCODE -ne 0) { throw '無法讀取資料庫結構版本（alembic current）；請檢查 DATABASE_PATH。' }
    } finally { Pop-Location }
    $revision = { param($Lines) @($Lines | ForEach-Object { if ("$_" -match '^\s*([0-9A-Za-z_]+)') { $Matches[1] } } | Sort-Object -Unique) }
    $headIds = & $revision $heads
    $currentIds = & $revision $current
    if (-not $headIds) { throw '找不到 migration head；請確認 backend/migrations 完整。' }
    return [pscustomobject]@{ Current = $currentIds; Heads = $headIds; AtHead = (($currentIds -join ',') -eq ($headIds -join ',')) }
}

function Get-MwbMigrationMessage {
    param($State)
    return "資料庫結構版本（$($State.Current -join ', ')）落後程式（$($State.Heads -join ', ')），未自動升級。請照 docs/部署與維運.md「部署順序」第 1–3 步：先備份、停止服務，並依「Migration 注意事項」在副本演練；完成後以 start-all.ps1 -ApplyMigrations 重新執行，或在 backend 執行 uv run alembic upgrade head。"
}

try {
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw '已有一鍵啟動正在執行，請等待完成。' }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) { throw '請先複製 .env.example 為 .env，並設定本機密碼與測試憑證。' }
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    $uv = (Get-Command uv.exe -ErrorAction Stop).Source
    Invoke-Step $node @('scripts/webhooks.mjs', 'resolve-ngrok') $projectRoot '確認 ngrok 執行檔（PATH、NGROK_PATH、LOCALAPPDATA）與 NGROK_AUTHTOKEN'
    Invoke-Step $node @('scripts/webhooks.mjs', 'prepare') $projectRoot '初始化 Webhook 簽章設定'
    Push-Location $projectRoot
    try {
        $port = & $node --input-type=module -e "import {readSettings,backendPort} from './scripts/webhooks.mjs'; console.log(backendPort(readSettings()))"
        if ($LASTEXITCODE -ne 0) { throw '後端連接埠設定不合法（BACKEND_INTERNAL_URL／APP_ORIGIN）。' }
    } finally { Pop-Location }
    $port = [int]$port
    $localUrl = "http://127.0.0.1:$port"
    $python = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
    $backend = Get-MwbProcess -Name backend -Root $projectRoot
    $gateway = Get-MwbProcess -Name gateway -Root $projectRoot
    $fingerprintFiles = @(
        Get-ChildItem -LiteralPath (Join-Path $projectRoot 'backend/app'), (Join-Path $projectRoot 'backend/migrations'), (Join-Path $projectRoot 'frontend/src') -File -Recurse | Where-Object { $_.Extension -in '.py', '.tsx', '.ts', '.css', '.json' }
        # plugin 版本與雜湊在後端匯入時讀取（agent_packages.PLUGIN_LATEST）；只發 plugin 新版也要重啟後端。
        Get-ChildItem -LiteralPath (Join-Path $projectRoot 'plugin') -File -Recurse
        Get-Item -LiteralPath (Join-Path $projectRoot '.env'), (Join-Path $projectRoot 'backend/pyproject.toml'), (Join-Path $projectRoot 'backend/uv.lock'), (Join-Path $projectRoot 'frontend/package-lock.json'), (Join-Path $projectRoot 'config/ngrok.yml'), (Join-Path $projectRoot 'config/ngrok-traffic-policy.json')
        Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.mjs' -File | Where-Object { $_.Name -notlike '*.test.mjs' }
    )
    $hashes = ($fingerprintFiles | Sort-Object FullName | Get-FileHash -Algorithm SHA256 | ForEach-Object Hash) -join ':'
    $fingerprintPath = Join-Path $runtime 'start-fingerprint.txt'
    $previous = if (Test-Path -LiteralPath $fingerprintPath) { (Get-Content -LiteralPath $fingerprintPath -Raw).Trim() } else { '' }
    $reload = $Restart -or $SuppressSystemAlerts -or $InstallDependencies -or $previous -ne $hashes
    if ($reload -and $backend -and -not $ApplyMigrations) {
        # 先確認不需要 migration 再停服務；否則新程式等升級時，正在供應的舊服務也被停掉。
        # 讀不到版本（例如套件尚未同步）時交給下方同步後的檢查決定。
        $state = $null
        try { $state = Get-MwbMigrationState -Python $python -Backend (Join-Path $projectRoot 'backend') } catch { }
        if ($state -and -not $state.AtHead -and $state.Current) { throw (Get-MwbMigrationMessage $state) }
    }
    if ($reload) {
        Stop-MwbProcess -Name gateway -Root $projectRoot
        Stop-MwbProcess -Name backend -Root $projectRoot
        $backend = $null; $gateway = $null
    }
    if (-not $backend -and -not (Test-Path -LiteralPath $fingerprintPath) -and -not [Console]::IsInputRedirected -and -not (Test-MwbPortFree -Port $port)) {
        # 第一次啟動才問：預設 8000 常被其他開發工具佔用。之後啟動（含開機自動啟動）沿用 .env，不再互動。
        $answer = Read-Host "連接埠 $port 已被其他程式佔用。要改用哪個連接埠（例如 8010）？直接按 Enter 取消"
        if (-not $answer) { throw "已取消。連接埠 $port 被佔用；可用 Get-NetTCPConnection -LocalPort $port 查是哪個程序。" }
        $newPort = 0
        if (-not [int]::TryParse($answer.Trim(), [ref]$newPort) -or -not (Test-MwbPortFree -Port $newPort)) { throw "連接埠 $answer 不能使用或也被佔用，未變更設定。" }
        Push-Location $projectRoot
        try {
            & $node --input-type=module -e "import {readSettings,saveSettings,portSettings} from './scripts/webhooks.mjs'; saveSettings(portSettings(readSettings(), Number(process.argv[1])))" $newPort
            if ($LASTEXITCODE -ne 0) { throw '無法把新的連接埠寫入 .env。' }
        } finally { Pop-Location }
        $port = $newPort
        $localUrl = "http://127.0.0.1:$port"
        Write-Host "已改用 $localUrl（.env 的 BACKEND_INTERNAL_URL 與 APP_ORIGIN 已更新）。"
    }
    if (-not $backend) { Assert-MwbPortFree -Port $port }
    if (-not $gateway) { Assert-MwbPortFree -Port 4040 }
    if (-not $backend) {
        Invoke-Step $uv @('sync', '--frozen') (Join-Path $projectRoot 'backend') '同步後端套件'
        # migration 前要先備份並在副本演練（docs/部署與維運.md）；一鍵啟動與開機自動啟動不能繞過這些檢查。
        $state = Get-MwbMigrationState -Python $python -Backend (Join-Path $projectRoot 'backend')
        if (-not $state.AtHead) {
            # 全新資料庫沒有版本、也沒有資料要保護，直接建立結構。
            if ($ApplyMigrations -or -not $state.Current) {
                Invoke-Step $python @('-m', 'alembic', 'upgrade', 'head') (Join-Path $projectRoot 'backend') '更新資料庫結構'
            } else { throw (Get-MwbMigrationMessage $state) }
        }
    }
    foreach ($name in @('frontend')) {
        $folder = Join-Path $projectRoot $name
        $lockHash = (Get-FileHash -LiteralPath (Join-Path $folder 'package-lock.json') -Algorithm SHA256).Hash
        $marker = Join-Path $runtime "$name-lock.txt"
        $lockChanged = (Test-Path -LiteralPath $marker) -and ((Get-Content -LiteralPath $marker -Raw).Trim() -ne $lockHash)
        if ($InstallDependencies -or $lockChanged -or -not (Test-Path -LiteralPath (Join-Path $folder 'node_modules/.package-lock.json'))) {
            Invoke-Step $npm @('ci', '--no-audit', '--no-fund') $folder "同步 $name 套件"
        }
        Set-Content -LiteralPath $marker -Value $lockHash -Encoding ASCII
    }
    if (-not $backend) {
        Invoke-Step $npm @('run', 'build') (Join-Path $projectRoot 'frontend') '建置後台畫面'
        $previousAlertOverride = $env:RECEIVE_HEALTH_ALERTS_ENABLED
        if ($SuppressSystemAlerts) { $env:RECEIVE_HEALTH_ALERTS_ENABLED = 'false' }
        try {
        $servicePid = Start-MwbDetached -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--app-dir', (Join-Path $projectRoot 'backend'), '--host', '127.0.0.1', '--port', ([string]$port), '--workers', '1', '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1') -WorkingDirectory (Join-Path $projectRoot 'backend') -StdoutPath (Join-Path $runtime 'backend.stdout.log') -StderrPath (Join-Path $runtime 'backend.stderr.log')
        } finally { $env:RECEIVE_HEALTH_ALERTS_ENABLED = $previousAlertOverride }
        Set-Content -LiteralPath (Join-Path $runtime 'backend.pid') -Value $servicePid -Encoding ASCII
        $started.Add('backend')
    }
    Wait-MwbHealth -Url "$localUrl/api/health" -Name backend -Root $projectRoot
    Push-Location $projectRoot
    try {
        $gatewaySeconds = & $node --input-type=module -e "import {readSettings,gatewayStartupSeconds} from './scripts/webhooks.mjs'; console.log(gatewayStartupSeconds(readSettings()))"
        if ($LASTEXITCODE -ne 0) { throw 'ngrok 等待時間設定不合法。' }
    } finally { Pop-Location }
    $gatewayReadyTimer = [Diagnostics.Stopwatch]::StartNew()
    $gatewayReused = [bool]$gateway
    if (-not $gateway) {
        $servicePid = Start-MwbDetached -FilePath $node -ArgumentList @((Join-Path $projectRoot 'scripts/webhooks.mjs'), 'up') -WorkingDirectory $projectRoot -StdoutPath (Join-Path $runtime 'gateway.stdout.log') -StderrPath (Join-Path $runtime 'gateway.stderr.log')
        Set-Content -LiteralPath (Join-Path $runtime 'gateway.pid') -Value $servicePid -Encoding ASCII
        $started.Add('gateway')
    }
    Wait-MwbHealth -Url 'http://127.0.0.1:4040/api/tunnels' -Name gateway -Root $projectRoot -Seconds ([int]$gatewaySeconds)
    # up 會驗證既有固定網址；等它完成後才宣告整體就緒。
    $deadline = [DateTime]::UtcNow.AddSeconds([int]$gatewaySeconds)
    do {
        if (-not (Get-MwbProcess -Name gateway -Root $projectRoot)) { throw 'Webhook 服務啟動失敗。' }
        $ready = Test-Path -LiteralPath (Join-Path $runtime 'gateway.stdout.log')
        if ($ready) { $ready = [bool](Select-String -LiteralPath (Join-Path $runtime 'gateway.stdout.log') -Pattern '固定網址驗收通過' -Quiet) }
        if ($gateway -or $ready) { break }
        if ([DateTime]::UtcNow.Second % 10 -eq 0) { Write-Host '等待固定網址驗收完成；進度見 .runtime/gateway.stdout.log。' }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $gateway -and -not $ready) { throw 'Webhook 固定網址驗收逾時；請檢查 .runtime/gateway.stdout.log、gateway.stderr.log 及 gateway-startup-tail.log 最後 12 行。' }
    $gatewayReadyTimer.Stop()
    # 公開邊界的關卡：重試後仍失敗就停止剛啟動的服務。
    if (-not (Invoke-StepWithRetry $node @('scripts/webhooks.mjs', 'check') $projectRoot '驗證 Webhook 路徑限制及 後端排程器')) {
        throw 'Webhook 公開邊界驗證重試後仍未通過；請依上方訊息處理後重新執行。'
    }
    Push-Location $projectRoot
    try {
        $tailscaleEnabled = & $node --input-type=module -e "import {readSettings} from './scripts/webhooks.mjs'; console.log(readSettings().TAILSCALE_ENABLED === 'true' ? 'true' : 'false')"
        if ($LASTEXITCODE -ne 0) { throw '無法讀取 Tailscale 設定。' }
    } finally { Pop-Location }
    if ($tailscaleEnabled -eq 'true') {
        # Tailscale 只影響內部 HTTPS 入口；暫時失敗不停止服務，本機網址仍可使用。
        if (-not (Invoke-StepWithRetry $node @('scripts/tailscale.mjs', 'check') $projectRoot '驗證 Tailscale HTTPS')) {
            Write-Warning "Tailscale HTTPS 驗證約 2 分鐘內仍未通過；服務維持執行，本機 $localUrl 可用。網路就緒後執行 node scripts/tailscale.mjs check 確認。"
        }
    }
    else { Write-Host 'Tailscale 尚未設定；登入後執行 node scripts/tailscale.mjs configure。' }
    Set-Content -LiteralPath $fingerprintPath -Value $hashes -Encoding ASCII
    $timing = [ordered]@{ utc=[DateTime]::UtcNow.ToString('o'); phase='start-all-ready'; seconds=[Math]::Round($gatewayReadyTimer.Elapsed.TotalSeconds, 3); reused=$gatewayReused }
    Add-Content -LiteralPath (Join-Path $runtime 'gateway-startup-times.jsonl') -Value ($timing | ConvertTo-Json -Compress) -Encoding UTF8
    $timingLabel = if ($gatewayReused) { '既有服務就緒檢查' } else { 'ngrok 就緒（含固定網址驗收）' }
    Write-Host "$timingLabel 耗時 $($timing.seconds) 秒；趨勢紀錄：.runtime/gateway-startup-times.jsonl"
    Write-Host "啟動完成：$localUrl （關閉此視窗不會停止服務）"
} catch {
    foreach ($name in $started) { try { Stop-MwbProcess -Name $name -Root $projectRoot } catch { } }
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
