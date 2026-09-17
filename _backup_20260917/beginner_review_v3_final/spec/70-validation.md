# 70 · 탐색적 통계 검증

담당: backtest.py. 근거: arch stationary bootstrap 문서, SciPy spearmanr, Bailey et al. The Probability of Backtest Overfitting (METHODOLOGY_AUDIT.md 참조).

- REQ-VAL-1: fwd_h=log(P[t+h]/P[t])는 종가 기반 연관성 통계이며 체결 가능한 전략 수익률이 아니다.
- REQ-VAL-2: horizon별 결측 수익률을 개별 처리; 120일 수익률 결측 때문에 20일 관측을 삭제하지 않는다.
- REQ-VAL-3: stationary bootstrap은 원 거래일 축을 재표집하고, 그 후 결측/조건 마스크를 적용한다. 레짐/구성 필터로 떨어진 날을 이웃한 거래일로 압축하지 않는다.
- REQ-VAL-4: 상수·비유한·정의 불가 IC는 None. 재표집 중 정의 불가 통계가 있으면 CI 산출 불가로 명시하고 유효 반복수 병기.
- REQ-VAL-5: n/h는 단순 비중첩 블록 수 참고값이지 유효 표본 크기 추정치가 아니다.
- REQ-VAL-6: 과거 결과 고정 결론 금지. CI는 다중검정 미보정의 탐색 결과로만 표기. 전체 기간 중앙값 레짐은 사후 분류라고 명시.
- AC-VAL-1: 상수 계열 None, 날짜 마스크 보존, horizon별 표본 수, 고정 결론 미출력을 합성 자료로 검증한다.
- 향후 표본외 기간, 거래 시점/보유기간, 거래비용, 선택된 전략 전체의 다중검정 범위는 사용자 결정 후 사전 고정한다.
