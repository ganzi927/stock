# combined_main.py 를 호출하기만 한다. 실행 판단은 전부 combined_main.py 안에 있다:
#   - 멱등: 같은 기준일(anchor)의 완결 리포트가 이미 있으면 즉시 종료(exit 0), AI 재호출 없음.
#   - 엄격: anchor 당일 옵션 EOD가 KRX에 아직 없으면 리포트를 만들지 않고 exit 3.
#           → 스케줄러의 다음 트리거(평일 07:30 / 부팅 / 저녁 20:00~23:00 슬롯)가 재시도하고,
#             KRX 야간 배치가 올라온 뒤 첫 실행에서 그날 리포트가 완성된다.
# 따라서 이 스크립트는 경계시각 계산 없이 그냥 매 트리거마다 한 번씩 실행하면 된다.

$ErrorActionPreference = "Stop"
$pythonExe  = "D:\workSpace\stock\venv\Scripts\python.exe"
$mainScript = "D:\workSpace\stock\combined_main.py"
$logDir     = "D:\workSpace\stock\reports"

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
& $pythonExe $mainScript
$code = $LASTEXITCODE

switch ($code) {
    0 { Write-Output "$stamp  OK (리포트 완결 또는 이미 존재)" }
    3 { Write-Output "$stamp  대기 — anchor 당일 옵션 EOD 미게시. 다음 트리거에 재시도." }
    2 { Write-Output "$stamp  오류 — anchor 를 잡을 시세가 캐시에 없음." }
    default { Write-Output "$stamp  종료코드 $code (예상치 못한 오류)." }
}

# 종료코드 3(대기)은 정상 흐름이므로 작업 스케줄러에 실패로 남기지 않는다.
if ($code -eq 3) { exit 0 } else { exit $code }
