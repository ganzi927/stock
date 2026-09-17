# 사양(spec) 관리 — 인덱스

이 디렉터리는 "오늘의 코스피" 시그널 파이프라인의 **정식 사양(normative spec)**을 모듈별로
관리한다. 산재된 방법론 문서(`README.md` / `RECONCILIATION.md` / `VALIDATION.md` /
`WORKPLAN*.md` / `DATA_INVENTORY.md`)에서 "무엇을 어떻게 계산하는가"의 계약만 뽑아
한곳에 고정한 것이다.

## 원칙

1. **코드가 기준이다.** 사양과 구현이 어긋나면 구현이 옳다고 보고 사양을 고친다(단,
   그 어긋남이 의도치 않은 것으로 판명되면 이슈로 등록). `indicators.py` 상단 주석의
   "불일치 시 코드가 기준" 규약을 spec 전체로 확장한 것.
2. **규범 표현.** "~한다 / ~여야 한다(SHALL)"로 계약을 적고, 배경·근거는 각주나
   "근거" 항목으로 분리한다.
3. **수치·상수는 심볼과 함께.** `PCT_WINDOW=252`, `CONTRACT_MULTIPLIER=250_000` 처럼
   코드 심볼명과 값을 같이 적어 grep 가능하게 한다.
4. **수용 기준(Acceptance)은 검증 코드에 연결.** 각 사양의 "수용 기준"은 가능하면
   `tests/test_math.py` / `backtest.py` / `VALIDATION.md`의 구체 항목을 가리킨다.
   아직 검증이 없는 항목은 `⚠ 미검증`으로 명시한다.
5. **사양 주도 개발 (SDD) — 모든 변경은 spec을 통해서만 이뤄진다.**
   프로젝트 루트 `CLAUDE.md`가 전체 규칙이며, 요약하면:

   | 단계 | 할 일 |
   |---|---|
   | ① 사양 먼저 | 바꿀 대상 spec 파일을 열어 REQ-*/INV-*/AC-*를 **원하는 최종 상태로 먼저 수정**. 새 동작이면 새 REQ 번호 부여 |
   | ② 구현 | spec을 만족하도록 코드 수정 |
   | ③ 검증 | 대응 AC 갱신, 필요 시 `tests/test_math.py`에 케이스 추가, `python tests/test_math.py` 통과 |
   | ④ 상태표 | 아래 상태표의 "마지막 정합 확인" 날짜·드리프트 칸 갱신 |
   | ⑤ 스냅샷 | 로직 변경 커밋 전 `_backup_YYYYMMDD/`에 관련 파일 스냅샷 |

   ①~⑤는 **한 커밋 안에서** 함께. 코드만 바뀌고 spec이 안 바뀐 커밋(또는 그 반대)은
   미완성으로 간주한다.

   **예외**(spec 갱신 불필요): 순수 리팩터링(동작 불변), 오타·주석·로그 문구,
   HTML/CSS 표현 변경, 의존성 버전 범프. 계산 결과·계약·exit code·파일 스키마가
   바뀌면 예외가 아니다.

## 파일 구성

| 파일 | 범위 | 담당 코드 |
|---|---|---|
| [`00-architecture.md`](00-architecture.md) | anchor 고정·엔트리포인트·exit code·멱등·게이트·탭·사이드카 | `combined_main.py`, `main.py`, `options_main.py`, `stock_options_main.py` |
| [`10-kfgi.md`](10-kfgi.md) | 한국형 공포탐욕지수 7개 지표: raw 정의·점수화·서브지수·TOTAL·CI·프록시 폴백 | `indicators.py`, `main.py`, `charts.py`, `report.py` |
| [`20-kospi200-options.md`](20-kospi200-options.md) | 코스피200 옵션 딜러 포지셔닝: 체인 파싱·r/q·그릭스·GEX/DEX/VEX/Charm·Zero Gamma·Wall·MaxPain·PoT·RR25·합성선물·시나리오 | `options_data.py`, `greeks.py`, `dealer_positioning.py`, `options_main.py`, `options_charts.py`, `options_report.py` |
| [`30-stock-options.md`](30-stock-options.md) | 삼성전자·SK하이닉스 개별주식 옵션 (20과의 차이만) | `stock_options_data.py`, `stock_options_main.py`, `dividends.py` |
| [`40-outlook-ai.md`](40-outlook-ai.md) | AI 코멘트·종합전망 탭: 프롬프트 계약·금지 규약·검증 게이트·비용 스위치 | `ai_commentary.py`, `outlook.py` |
| [`50-data-pipeline.md`](50-data-pipeline.md) | 데이터 소스·캐시·백필·품질 한계·as_of 트렁케이션 | `naver_data.py`, `krx_api.py`, `krx_market.py`, `ecos_data.py`, `dividends.py` |
| [`60-automation.md`](60-automation.md) | Windows 작업 스케줄러 트리거·`run_daily.ps1`·재시도 | `register_task.ps1`, `run_daily.ps1` |
| [`99-glossary.md`](99-glossary.md) | 용어·부호 규약·단위 | — |

## 상태표

| spec | 상태 | 마지막 정합 확인 | 알려진 코드 vs 문서 드리프트 |
|---|---|---|---|
| 00-architecture | STABLE | 2026-09-17 | report_contract_version=4 및 AI 종합·만기 관찰 레벨 계약 반영 |
| 10-kfgi | STABLE | 2026-09-17 | 역산 점수·P/C 당일 raw/MA5·Strength 정의 정합. 과거 RECONCILIATION.md의 창/평활은 현행 사양과 다름 |
| 20-kospi200-options | STABLE | 2026-09-17 | 가격 경로 계약을 관측 레벨·정의·한계로 교체; 모델/데이터 한계는 METHODOLOGY_AUDIT.md |
| 30-stock-options | STABLE | 2026-09-17 | 관찰가격/개인 계산 분리, 입력 변경 시 결과 초기화; 위클리 개별주식옵션 미통합 |
| 40-outlook-ai | STABLE | 2026-09-17 | 종합 AI 1회·실패 시 결정론 대체; 네 상품의 만기별 상·하단 관찰 레벨 명시 |
| 50-data-pipeline | STABLE | 2026-09-08 | KOSDAQ(`ksq_bydd_trd`) 미이용신청 → KOSPI만 |
| 60-automation | STABLE | 2026-09-10 | 없음 (아침 트리거 07:30→08:00, 수동 실행 `리포트생성.cmd` 추가 — REQ-AUTO-2) |
| 99-glossary | STABLE | 2026-09-08 | — |

상태값: `DRAFT`(초안, 미검토) → `STABLE`(코드와 정합 확인됨) → `TODO`(작성 예정).

| 70-validation | STABLE | 2026-09-16 | 합성자료 테스트만 완료; 실데이터 재검증 필요 |

[70-validation.md](70-validation.md): backtest.py의 탐색 통계 계약.

2026-09 감사 회귀 테스트: `python -m unittest discover -s tests -p test_audit.py -v`.

## 품질 게이트 v2

[80-quality.md](80-quality.md)가 이전 00/10/20/30/40/50/70의 충돌하는 사용범위 규약보다 우선한다. 정합 확인: 2026-09-17. 상태 STABLE(코드·fixture 정합), 실데이터/공식 기준자료 완전성은 미검증.

담당: data_quality.py, reference_data.py, validate_inputs.py 및 각 진입점/리포트/AI.

2026-09-17 초보 투자 보조 리뷰 반영: 종가·단위 우선 노출, 기술 품질표 접힘과 핵심 경고 유지,
관측 레벨 계약, 종합 AI와 실패 대체, 만기별 상·하단 관찰 레벨, 역산 점수 설명 및 계산기 입력 변경 회귀 검증.
`tests/test_math.py` 전체 통과, `unittest discover -s tests -p "test_*.py"` 41개 통과.
