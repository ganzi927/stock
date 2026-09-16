# 60 · 자동화 (Windows 작업 스케줄러 + 수동 실행)

담당 코드: `register_task.ps1`(등록), `run_daily.ps1`(스케줄러 래퍼),
`리포트생성.cmd`(사용자 수동 실행). 판단 로직은 전부 `combined_main.py` 안에 있고
([00-architecture.md](00-architecture.md)) 이 스크립트들은 호출·재시도·결과 안내만 한다.

---

## A. `run_daily.ps1`

- `venv\Scripts\python.exe combined_main.py` 실행. 경계시각 계산 **없음** — 매 트리거마다
  한 번씩 그냥 실행.
- `$LASTEXITCODE` 매핑:
  - `0` → "OK (리포트 완결 또는 이미 존재)"
  - `3` → "대기 — anchor 당일 옵션 EOD 미게시" → **`exit 0`** (스케줄러에 실패로 안 남김)
  - `2` → "오류 — anchor 시세 없음" → `exit 2`
  - 그 외 → `exit <code>`

---

## A2. `리포트생성.cmd` — 수동 실행 (더블클릭)

**REQ-AUTO-2 (수동 실행 경로).** 사용자가 리포트가 없는 것을 확인했을 때 파일 하나를
더블클릭해 즉시 생성을 시도할 수 있어야 한다. `리포트생성.cmd`는 저장소 루트에 있고:

- `venv\Scripts\python.exe combined_main.py` 를 인자 없이 1회 실행한다(스케줄러 경로와
  동일 — anchor·게이트·멱등 판단은 전부 `combined_main.py`).
- `%ERRORLEVEL%` 를 사람이 읽을 안내로 매핑한다:
  - `0` → "완료" 출력 후 `reports\` 의 **가장 최근 통합 리포트**(`20*-*-*.html`,
    `options-*`/`stock-options-*` 접두 제외)를 기본 브라우저로 연다.
  - `3` → "KRX에 아직 옵션 EOD가 안 올라옴 — 잠시 후 다시 실행" 안내, 파일 안 엶.
  - `2` → "기준일 시세 캐시 없음" 안내.
  - 그 외 → 종료코드와 함께 오류 안내.
- 콘솔 코드페이지를 UTF-8(`chcp 65001`)로 두고, 끝에서 `pause` 로 창을 유지해
  사용자가 결과를 읽을 수 있게 한다.
- `run_daily.ps1` 과 달리 `exit 3` 을 `0` 으로 바꾸지 않는다(스케줄러 기록용이 아니므로).

---

## B. `register_task.ps1` — 작업 "StockDailyReport"

**REQ-AUTO-1 (안전 등록).** 새 작업 `Register-ScheduledTask -Force` 가 성공한 **뒤에만**
옛 이름(`"KFGI Daily Report"`)을 제거한다. 등록 실패 시 기존 작업 미변경·중단.

### 트리거
| 트리거 | 시각 | 목적 |
|---|---|---|
| 평일 저녁 | 20:00부터 30분 간격 3시간(20:00 / 20:30 / … / 23:00) | 옵션 EOD 대기 슬롯. KRX 야간 배치 전이라 대개 `exit 3`(정상) |
| 매일 아침 | **08:00** | **핵심** — KRX 야간 배치 후 그날 첫 실행. 전날 거래일 리포트가 여기서 완성 (06:00 → 07:30 → 게시 지연 누적으로 08:00 재상향; 2026-09-08·09 기준 KRX 게시가 08:00~09:00대). 08:00에도 아직이면 `리포트생성.cmd` 수동 실행으로 보완 |
| 부팅 | 시작 3분 후(`PT3M`) | 08:00에 PC가 꺼져 있던 경우 |

### 설정
- `LogonType S4U`, `RunLevel Limited` — 로그인 안 한 잠금화면에서도 실행, 암호 저장 불필요.
- `-WakeToRun` — 절전 상태면 깨움(전원 옵션 "절전 모드 해제 타이머 허용" 필요; 최대
  절전/완전 종료는 못 깨움 → 07:30·부팅 트리거가 커버).
- `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable`.
- `-RestartCount 3 -RestartInterval 10분`, `-ExecutionTimeLimit 2시간`,
  `-MultipleInstances IgnoreNew`.

---

## C. 왜 이 구조인가 (근거)

`combined_main.py`가 **멱등 + 엄격 게이트**라, 여러 트리거가 겹쳐 실행돼도:
- 완결본이 있으면 즉시 `exit 0`(AI 재호출 없음).
- 옵션 EOD가 없으면 `exit 3`으로 아무것도 안 만들고 다음 트리거를 기다림.

→ 스케줄러 쪽은 "충분히 자주 시도"만 하면 되고 시각 정밀도가 필요 없다.

---

## D. 수용 기준

- **AC-AUTO-1.** `Start-ScheduledTask -TaskName StockDailyReport` 를 옵션 EOD 없는
  시간대에 실행 → 작업 결과 성공(0), `reports/<anchor>.pending.json` attempts 증가,
  `.html` 미생성.
- **AC-AUTO-2.** 야간 배치 후 08:00 실행 1회로 전 거래일 `reports/<date>.html` +
  `.meta.json`(`options_complete: true`) 생성.
- **AC-AUTO-3.** `register_task.ps1` 재실행(멱등) — 기존 트리거/설정 덮어쓰고 옛 이름
  정리, 에러 없음. 등록 후 `Get-ScheduledTask` 의 아침 트리거 `StartBoundary` 시각이
  `08:00`.
- **AC-AUTO-4.** 옵션 EOD 게시 후 `리포트생성.cmd` 더블클릭 1회 → `combined_main.py`
  `exit 0`, `reports/<anchor>.html` 존재, 해당 파일이 브라우저로 열림. EOD 미게시
  시간대에 실행하면 "잠시 후 다시" 안내만 출력하고 창은 `pause` 로 유지.
