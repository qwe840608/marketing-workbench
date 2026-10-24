Set-StrictMode -Version Latest

$script:MwbNativeProcessQuery = $false
function Get-MwbProcessInfo {
    param([string]$Root, [int]$ProcessId = 0)
    if (-not $script:MwbNativeProcessQuery) {
        try {
            if ($ProcessId) { return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop }
            return Get-CimInstance Win32_Process -ErrorAction Stop
        } catch { $script:MwbNativeProcessQuery = $true }
    }
    $python = Join-Path $Root 'backend/.venv/Scripts/python.exe'
    $arguments = @((Join-Path $Root 'scripts/process_info.py'))
    if ($ProcessId) { $arguments += @('--pid', [string]$ProcessId) }
    $value = & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw '無法核對程序身分；未停止或接管任何程序。' }
    return ($value | ConvertFrom-Json)
}

function ConvertTo-MwbUtcTime {
    param($Value)
    # CIM 回傳 DateTime；process_info.py 備援回傳 epoch 秒數，兩者統一成 UTC 才能比較。
    if ($null -eq $Value) { return $null }
    if ($Value -is [DateTime]) { return $Value.ToUniversalTime() }
    $seconds = 0.0
    if ([double]::TryParse([string]$Value, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$seconds)) {
        return [DateTime]::new(1970, 1, 1, 0, 0, 0, [DateTimeKind]::Utc).AddSeconds($seconds)
    }
    return $null
}

function Remove-MwbPidFile {
    param([string]$Name, [string]$Root)
    $pidPath = Join-Path $Root ".runtime/$Name.pid"
    if (Test-Path -LiteralPath $pidPath) { Remove-Item -LiteralPath $pidPath -Force }
}

function Get-MwbProcess {
    param([string]$Name, [string]$Root)
    $pidPath = Join-Path $Root ".runtime/$Name.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) { return $null }
    $servicePid = 0
    if (-not [int]::TryParse((Get-Content -LiteralPath $pidPath -Raw).Trim(), [ref]$servicePid)) {
        throw "$Name 的 PID 紀錄不合法；未停止任何程序。"
    }
    $service = Get-MwbProcessInfo -Root $Root -ProcessId $servicePid
    if (-not $service) { return $null }
    # 重開機後 PID 重新分配：比 PID 紀錄還晚建立的程序不可能是當初寫入的服務。
    # 視為過期紀錄移除；否則開機自動啟動每次都被「PID 已由其他程序使用」擋住，永遠無法恢復。
    # 寬限幾秒只為了容許檔案時間的精度，正常寫入一定晚於程序建立。
    $createdUtc = ConvertTo-MwbUtcTime $service.CreationDate
    if ($createdUtc -and $createdUtc -gt (Get-Item -LiteralPath $pidPath).LastWriteTimeUtc.AddSeconds(5)) {
        Remove-Item -LiteralPath $pidPath -Force
        return $null
    }
    $signature = if ($Name -eq 'backend') { 'uvicorn app.main:app' } elseif ($Name -eq 'comments-only') { (Join-Path $Root 'scripts/run-meta-comments.mjs') } else { (Join-Path $Root 'scripts/webhooks.mjs') }
    if (-not $service.CommandLine -or $service.CommandLine.IndexOf($Root, [StringComparison]::OrdinalIgnoreCase) -lt 0 -or $service.CommandLine.IndexOf($signature, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "$Name 的 PID 已由其他程序使用；未停止或接管。"
    }
    return $service
}

function Stop-MwbProcess {
    param([string]$Name, [string]$Root)
    $service = Get-MwbProcess -Name $Name -Root $Root
    if (-not $service) {
        # 程序已不存在（或紀錄已過期），留下的 PID 檔只會在下次被誤認；一併清掉。
        Remove-MwbPidFile -Name $Name -Root $Root
        return
    }
    $snapshot = @(Get-MwbProcessInfo -Root $Root)
    $ownedIds = [System.Collections.Generic.List[int]]::new()
    $ownedIds.Add([int]$service.ProcessId)
    for ($index = 0; $index -lt $ownedIds.Count; $index++) {
        $parent = $snapshot | Where-Object ProcessId -eq $ownedIds[$index] | Select-Object -First 1
        foreach ($child in $snapshot) {
            # Windows 會重用 PID：父程序結束後，其 PID 可能被無關程序拿走，原本的子程序（例如
            # 操作人的終端或編輯器）看起來就像它的子程序。真正的子程序必定晚於父程序建立。
            if ($child.ParentProcessId -eq $ownedIds[$index] -and -not $ownedIds.Contains([int]$child.ProcessId) -and
                $parent -and $child.CreationDate -ge $parent.CreationDate) { $ownedIds.Add([int]$child.ProcessId) }
        }
    }
    # 子程序都來自已驗證的根程序；只停止同一次建立的程序，防止 PID 重用。
    $stoppedIds = [System.Collections.Generic.List[int]]::new()
    for ($index = $ownedIds.Count - 1; $index -ge 0; $index--) {
        $old = $snapshot | Where-Object ProcessId -eq $ownedIds[$index] | Select-Object -First 1
        # Windows 管理的 console host 由所屬程序退出時回收，不直接終止系統 console host。
        if ($old -and $old.Name -eq 'conhost.exe') { continue }
        $current = Get-MwbProcessInfo -Root $Root -ProcessId $ownedIds[$index]
        if ($current -and $old -and $current.CreationDate -eq $old.CreationDate) {
            try { Stop-Process -Id $current.ProcessId -ErrorAction Stop; $stoppedIds.Add([int]$current.ProcessId) }
            catch {
                # 身分檢查與停止之間可能自行結束；其他錯誤仍交由操作人處理。
                if ($_.FullyQualifiedErrorId -notlike 'NoProcessFoundForGivenId,Microsoft.PowerShell.Commands.StopProcessCommand*') { throw }
            }
        }
    }
    # Stop-Process 只送出終止要求就返回；等程序真的結束、釋放連接埠，重啟時才不會誤判埠被佔用。
    if ($stoppedIds.Count) {
        try { Wait-Process -Id $stoppedIds.ToArray() -Timeout 10 -ErrorAction SilentlyContinue } catch { }
    }
    Remove-MwbPidFile -Name $Name -Root $Root
}

function ConvertTo-MwbCommandArgument {
    param([string]$Value)
    # cmd.exe 會展開 % 與解讀雙引號；含這些字元時無法安全包進 cmd /c，交由呼叫端改走備援。
    if ($Value.IndexOfAny([char[]]'"%') -ge 0) { throw "參數含有 cmd.exe 無法安全處理的字元：$Value" }
    if ($Value -match '^[A-Za-z0-9_.:=-]+$') { return $Value }
    # 路徑一律加引號：專案根目錄可能含空白或 & 等 cmd 特殊字元。
    return '"' + $Value + '"'
}

function Start-MwbDetached {
    param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory, [string]$StdoutPath, [string]$StderrPath)
    # Start-Process 建立的程序留在呼叫端的 job object 裡（Claude 背景 shell、工作排程器的開機工作），
    # 那個工作結束時服務會被一起關掉（2026-10-18 停擺過）。改由 WMI 建立，父程序是 WmiPrvSE，不屬於任何 job。
    if (-not $script:MwbNativeProcessQuery) {
        try {
            $parts = @((ConvertTo-MwbCommandArgument $FilePath)) + @($ArgumentList | ForEach-Object { ConvertTo-MwbCommandArgument $_ })
            # 以 cmd 包一層才能把輸出導到日誌（覆寫，與原本 -RedirectStandard* 相同）；/s 讓最外層引號被原樣剝除。
            $inner = ($parts -join ' ') + ' > ' + (ConvertTo-MwbCommandArgument $StdoutPath) + ' 2> ' + (ConvertTo-MwbCommandArgument $StderrPath)
            $cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
            $commandLine = '"' + $cmd + '" /d /v:off /s /c "' + $inner + '"'
            # WMI 建立的程序拿到的是使用者預設環境，不是目前 shell 的；明確傳入整份環境，
            # 讓操作人臨時設定的 RECEIVE_HEALTH_ALERTS_ENABLED 等覆寫與 Start-Process 一樣生效。
            $environment = [string[]]@(Get-ChildItem Env: | ForEach-Object { $_.Name + '=' + $_.Value })
            $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0; EnvironmentVariables = $environment } -ErrorAction Stop
            $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $commandLine; CurrentDirectory = $WorkingDirectory; ProcessStartupInformation = $startup } -ErrorAction Stop
            if ($result.ReturnValue -eq 0 -and $result.ProcessId) { return [int]$result.ProcessId }
            Write-Warning "無法以獨立程序啟動（Win32_Process 回傳 $($result.ReturnValue)）；改用 Start-Process，關閉啟動它的視窗或工作時服務可能一起結束。"
        } catch {
            Write-Warning "無法以獨立程序啟動（$($_.Exception.Message)）；改用 Start-Process，關閉啟動它的視窗或工作時服務可能一起結束。"
        }
    }
    $quoted = @($ArgumentList | ForEach-Object { if ($_ -match '^[A-Za-z0-9_.:=-]+$') { $_ } else { '"' + $_ + '"' } })
    $process = Start-Process -FilePath $FilePath -ArgumentList $quoted -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
    return $process.Id
}

function Assert-MwbPortFree {
    param([int]$Port, [int]$Seconds = 5)
    # 剛停止的服務可能還在釋放連接埠；短暫重試，避免重啟時誤判為被其他程式佔用。
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ($true) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
        try { $listener.Start(); return }
        catch { if ([DateTime]::UtcNow -ge $deadline) { throw "連接埠 $Port 已被佔用或無法綁定；未停止或接管。可能是另一個資料夾的工作檯或其他程式正在使用，用 Get-NetTCPConnection -LocalPort $Port 查是哪個程序。" } }
        finally { $listener.Stop() }
        Start-Sleep -Milliseconds 250
    }
}

function Wait-MwbHealth {
    param([string]$Url, [string]$Name, [string]$Root, [int]$Seconds = 60)
    $startedAt = [DateTime]::UtcNow
    $nextProgress = $startedAt
    $deadline = $startedAt.AddSeconds($Seconds)
    do {
        if (-not (Get-MwbProcess -Name $Name -Root $Root)) { $detail = ''
            if ($Name -eq 'gateway') {
                $log = Join-Path $Root '.runtime/gateway.stderr.log'
                if (Test-Path -LiteralPath $log) { $detail = (Get-Content -LiteralPath $log -Encoding UTF8 | Where-Object { $_ -match '啟動失敗|找不到 ngrok|NGROK_AUTHTOKEN|逾時|已等待' } | Select-Object -Last 1) }
            }
            throw "$Name 啟動失敗：$detail；請檢查 .runtime 的服務日誌。" }
        try {
            $result = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($result.StatusCode -eq 200) { return }
        } catch { }
        if ([DateTime]::UtcNow -ge $nextProgress) {
            $elapsed = [int]([DateTime]::UtcNow - $startedAt).TotalSeconds
            Write-Host "$Name 已等待 $elapsed 秒；啟動進度見 .runtime/$Name.stdout.log。"
            $nextProgress = [DateTime]::UtcNow.AddSeconds(10)
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$Name 未就緒，已等待 $Seconds 秒；請檢查 .runtime/$Name.stdout.log 與 .runtime/$Name.stderr.log 的最後幾行。"
}
