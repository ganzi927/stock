# 00 · 아키텍처 — 실행 계약

담당 코드: `combined_main.py`(운영 진입점), `main.py` / `options_main.py` /
`stock_options_main.py`(단독 진입점), `report.py`(페이지 셸).

---

## A. 리포트 산출물

- 운영 산출물은 **단일 HTML 파일** `reports/<anchor>.html`. 이미지는 base64 내장이라
  파일 하나로 공유·보관 가능해야 한다.
- 탭 구성(순서 고정): `fgi`(공포탐욕지수) → `kospi-opt`(코스피200 옵션) →
  `stock-opt`(삼성전자·SK하이닉스) → `outlook`(종합 전망).
- `stock-opt` 탭은 개별주식 옵션 데이터가 없으면 생략한다.
- `outlook` 탭은 다음 중 하나라도 참이면 생략한다: `ANTHROPIC_API_KEY` 없음,
  `KFGI_AI` 가 off, LLM 응답이 `max_tokens`에서 잘림, `fgi_facts`가 None.
- 단독 진입점은 각각 별도 파일을 만든다:
  `reports/<date>.html`(main), `reports/options-<date>.html`,
  `reports/stock-options-<date>.html`.

---

## B. Anchor(기준일) 고정 — 핵심 불변조건

**INV-ARCH-1.** 하나의 리포트는 **하나의 거래일 `anchor`**에 완전히 고정된다.
공포탐욕지수·코스피200 옵션·개별주식 옵션·헤더·종합전망이 전부 그 `anchor` 마감 기준.

- `anchor` = `--as-of` 이하의 **마지막 거래일**. 기준 시계는 `cache/kospi200.csv`
  (`_resolve_anchor`, `combined_main.py:59`).
- `--as-of` 기본값은 오늘(`date.today()`).
- 과거 거래일로 (재)생성 시, 캐시에 그 이후 데이터가 이미 들어와 있어도 모든 지표
  시계열을 `date <= anchor` 로 트렁케이트한다(`main._truncate_asof`). 트렁케이트는
  롤링 통계 계산 **이후**에 하므로 look-ahead가 없다.
- FGI 탭 실제 사용일 `fgi_as_of`가 `anchor`와 다르면(시세 캐시 지연) 경고를 출력하되
  리포트는 생성한다.

---

## C. Exit code 계약

| 심볼 | 값 | 의미 | run_daily.ps1 처리 |
|---|---|---|---|
| `EXIT_OK` | 0 | 리포트 완결 생성 **또는** 멱등 종료(이미 완결본 존재) | OK |
| `EXIT_NO_PRICE` | 2 | `anchor`를 잡을 시세가 `cache/kospi200.csv`에 없음 | 오류로 전파(exit 2) |
| `EXIT_OPTIONS_PENDING` | 3 | `anchor` 당일 옵션 EOD가 KRX Open API에 아직 없음 | **정상 흐름** — `exit 0`으로 매핑, 스케줄러에 실패로 안 남김 |

**REQ-ARCH-1 (엄격 게이트).** `anchor` 당일 정규월물 옵션 체인
(`fetch_option_chain(anchor, REGULAR_PROD)`)이 비어 있으면 리포트를 **생성하지 않고**
`exit 3`. 이전 거래일 데이터로 조용히 폴백하지 **않는다**.

**REQ-ARCH-2 (옵션 우선 생성).** 옵션 섹션(`generate_options_sections(require_exact=True)`)을
가장 먼저 만든다. 반환이 `not option_sections or not opt_exact or opt_bas_dd != anchor`
중 하나라도 참이면 리포트를 쓰지 않고 `exit 3`("옵션 없는 반쪽 리포트" 금지).

**REQ-ARCH-3 (멱등).** `--force`가 없고, `reports/<anchor>.html`이 존재하고,
`reports/<anchor>.meta.json`의 `options_complete == true`이면 AI 재호출 없이 즉시 `exit 0`.

---

## D. 사이드카 파일

`reports/` 아래, `anchor` ISO 날짜를 파일명 접두로.

### `<anchor>.meta.json` (성공 시 기록, `pending.json`은 삭제)
```
anchor              : "YYYY-MM-DD"
fgi_as_of           : "YYYY-MM-DD" | null    (FGI 탭이 실제로 쓴 마지막 거래일)
option_bas_dd       : "YYYY-MM-DD" | null    (옵션 섹션 기준일; anchor와 같아야 함)
options_complete    : true                   (멱등 가드가 읽는 키)
has_stock_options   : bool
has_outlook         : bool
total_kfgi          : float | null
generated_at        : ISO8601 (타임존 포함)
attempts            : int   (pending 누적 시도 + 1)
as_of_requested     : "YYYY-MM-DD"           (--as-of 원값)
```

### `<anchor>.pending.json` (게이트 미통과 시 관측용)
```
attempts     : int
first_seen   : ISO8601
last_attempt : ISO8601
```

---

## E. 환경·부트스트랩

- `.env`는 `main._load_dotenv`가 읽는다(`os.environ.setdefault` — 기존 환경변수
  우선). 키: `KRX_API_KEY`(옵션·시장), `ECOS_API_KEY`(신용스프레드·채권),
  `ANTHROPIC_API_KEY`(AI), `KFGI_AI`(LLM 하드 오프).
- 모든 진입점은 stdout/stderr를 `utf-8`(errors=replace)로 재설정한다 —
  Windows cp949 콘솔에서 유니코드 출력이 파이프라인을 죽이지 않도록.
- FGI 계산용 시세 백필: `HIST_DAYS = 900` (`main.generate_fgi_section`),
  `combined_main`은 `kospi200.csv`를 `min_days=900`으로 확보.

---

## F. 수용 기준

- **AC-ARCH-1.** `python combined_main.py --as-of <완결일>` 두 번 연속 실행 → 두 번째는
  "이미 완결된 리포트가 있습니다" 출력 + `exit 0`, AI 호출 0회.
- **AC-ARCH-2.** `KRX_API_KEY` 미설정 상태로 `combined_main.py` → 옵션 체인 빈값 →
  `exit 3`, `reports/<anchor>.html` 미생성, `pending.json` attempts 증가.
- **AC-ARCH-3.** 생성된 리포트의 헤더 날짜·각 옵션 섹션 `expiry_label`의 "기준일"·
  `meta.json`의 `anchor`/`option_bas_dd`가 모두 동일.
- **AC-ARCH-4 (⚠ 자동화 미검증).** `--as-of` 과거일 재생성 결과가 그 당시 실시간
  생성본과 동일해야 함 — 회귀 테스트 스크립트 없음, 수동 확인.
