# 60 · 자동화 (Windows 작업 스케줄러)

담당 코드: `register_task.ps1`(등록), `run_daily.ps1`(래퍼). 판단 로직은 전부
`combined_main.py` 안에 있고([00-architecture.md](00-architecture.md)) 이 스크립트들은
호출·재시도만 한다.

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

## B. `register_task.ps1` — 작업 "StockDailyReport"

**REQ-AUTO-1 (안전 등록).** 새 작업 `Register-ScheduledTask -Force` 가 성공한 **뒤에만**
옛 이름(`"KFGI Daily Report"`)을 제거한다. 등록 실패 시 기존 작업 미변경·중단.

### 트리거
| 트리거 | 시각 | 목적 |
|---|---|---|
| 평일 저녁 | 20:00부터 30분 간격 3시간(20:00 / 20:30 / … / 23:00) | 옵션 EOD 대기 슬롯. KRX 야간 배치 전이라 대개 `exit 3`(정상) |
| 매일 아침 | **07:30** | **핵심** — KRX 야간 배치 후 그날 첫 실행. 전날 거래일 리포트가 여기서 완성 (과거 06:00 → 게시 지연으로 07:30 상향) |
| 부팅 | 시작 3분 후(`PT3M`) | 07:30에 PC가 꺼져 있던 경우 |

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
- **AC-AUTO-2.** 야간 배치 후 07:30 실행 1회로 전 거래일 `reports/<date>.html` +
  `.meta.json`(`options_complete: true`) 생성.
- **AC-AUTO-3.** `register_task.ps1` 재실행(멱등) — 기존 트리거/설정 덮어쓰고 옛 이름
  정리, 에러 없음.
