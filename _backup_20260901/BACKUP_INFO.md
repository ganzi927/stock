# 백업 스냅샷 2026-09-01

WORKPLAN2 (필수 + D/A/B/C) 작업 완료 시점.

## 포함
- 모든 최상위 *.py, *.md
- tests/test_math.py
- requirements.txt, .env.example

## 미포함 (용량/민감)
- .env (API 키)
- cache/, reports/, uploads/, venv/, __pycache__/
- 이전 _backup_* 디렉터리

## 복원
개별 파일을 최상위로 복사. 예:
  cp _backup_20260901/dealer_positioning.py ./dealer_positioning.py

## 검증 상태 (이 스냅샷)
- tests/test_math.py: 25/25 통과
- combined_main.py / main.py / options_main.py / stock_options_main.py / backtest.py 정상 실행
