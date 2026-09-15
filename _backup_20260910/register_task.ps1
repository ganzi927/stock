# 잠금화면/로그아웃/절전 상태에서도 리포트가 자동 생성되도록 작업 스케줄러에 등록.
#
# 실행 방법 (둘 중 아무거나):
#   - 파일 우클릭 → "PowerShell로 실행"  (아래 자동 승격 코드가 UAC 창을 띄움)
#   - 관리자 PowerShell 에서:  powershell -ExecutionPolicy Bypass -File .\register_task.ps1
#
# 안전장치: 새 작업 등록이 성공한 뒤에야 옛 작업을 지운다. 등록이 실패하면
#          기존 작업을 건드리지 않고 중단한다. (-Force 라서 여러 번 재실행해도 안전)
#
# 트리거
#   - 평일 20:00 + 30분 간격 3시간 반복 (20:00 / 20:30 / ... / 23:00)
#       재부팅이 20:00을 걸쳐도 다음 슬롯에 잡힘. KRX 옵션 EOD 는 보통 이 시간대엔 아직
#       없어서(야간 배치) 이 슬롯들은 대부분 "대기(exit 3)"로 끝난다 — 정상이다.
#   - 매일 07:30 보정 (핵심): KRX 야간 배치가 올라온 뒤 그날 첫 실행. 여기서 전날 거래일
#       리포트가 완성된다. (전에는 06:00이었음 — KRX 게시가 그보다 늦을 수 있어 07:30으로.)
#   - 부팅 3분 후 (07:30에 PC가 꺼져 있다가 그 뒤에 켠 경우, 켜자마자 한 번 시도)
#   combined_main.py 가 멱등이라 여러 번 실행돼도 완결 리포트가 있으면 즉시 종료한다.
#
# 설정
#   - LogonType S4U : 로그인 안 한 잠금화면 상태에서도 실행. 암호 저장 불필요.
#   - WakeToRun     : 절전(sleep) 상태면 깨워서 실행.
#       ※ 전원 옵션에서 "절전 모드 해제 타이머 허용"이 켜져 있어야 실제로 깨어남 (스크립트 끝의 powercfg 참고).
#         최대 절전(hibernate)/완전 종료는 못 깨움 → 06:00 / 부팅 트리거가 커버.
#   - 배터리 모드에서도 시작/유지, StartWhenAvailable, 실패 시 10분 간격 3회 재시도.

# ---------------------------------------------------------------------------
# 0) 관리자 권한 자동 승격
# ---------------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "관리자 권한이 필요합니다. UAC 창에서 '예'를 누르세요..." -ForegroundColor Yellow
    Start-Process powershell.exe -Verb RunAs -ArgumentList `
        "-NoExit","-NoProfile","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`""
    return
}

$ErrorActionPreference = "Stop"

$taskName    = "StockDailyReport"
$oldNames    = @("KFGI Daily Report")   # 등록 성공 후 정리할 옛 이름
$workDir     = "D:\workSpace\stock"
$scriptPath  = "$workDir\run_daily.ps1"

# ---------------------------------------------------------------------------
# 1) 작업 구성요소
# ---------------------------------------------------------------------------
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`"" `
    -WorkingDirectory $workDir

$tEvening = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 8:00PM
$tEvening.Repetition = (New-ScheduledTaskTrigger -Once -At 8:00PM `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 3)).Repetition

$tMorning = New-ScheduledTaskTrigger -Daily -At 7:30AM

$tBoot = New-ScheduledTaskTrigger -AtStartup
$tBoot.Delay = "PT3M"

$triggers = @($tEvening, $tMorning, $tBoot)

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType S4U -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -WakeToRun `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

# ---------------------------------------------------------------------------
# 2) 새 작업 등록 (성공해야 다음 단계로)
# ---------------------------------------------------------------------------
try {
    Register-ScheduledTask -TaskName $taskName `
        -Action $action -Trigger $triggers -Principal $principal -Settings $settings `
        -Description "코스피200 옵션/KFGI 통합 리포트 자동 생성 (잠금/로그아웃/절전 상태 실행)" `
        -Force | Out-Null
    Write-Host "등록 완료: '$taskName'" -ForegroundColor Green
} catch {
    Write-Host "등록 실패 — 기존 작업은 그대로 둡니다:" -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    return
}

# ---------------------------------------------------------------------------
# 3) 옛 작업 정리 (등록 성공 후에만)
# ---------------------------------------------------------------------------
foreach ($n in $oldNames) {
    if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false
        Write-Host "기존 작업 제거: '$n'"
    }
}

# ---------------------------------------------------------------------------
# 4) 확인 출력
# ---------------------------------------------------------------------------
Write-Host ""
Get-ScheduledTaskInfo -TaskName $taskName | Format-List NextRunTime, LastRunTime, LastTaskResult
Write-Host "즉시 테스트:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host ""
Write-Host "※ 절전 상태에서 깨우려면 (관리자 창에서 한 번):"
Write-Host "   powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1"
Write-Host "   powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1"
Write-Host "   powercfg /SETACTIVE SCHEME_CURRENT"
