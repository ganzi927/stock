"""매일 실행 (운영용): KFGI + 코스피200 옵션 + 개별주식 옵션을 탭으로 구분된
하나의 HTML로 합쳐서 생성.

사용법:
    python combined_main.py   # reports/YYYY-MM-DD.html 하나에 탭 3개로 전부 담김

run_daily.ps1이 이 스크립트를 호출한다. 개별적으로 보고 싶으면 main.py /
options_main.py / stock_options_main.py를 각각 직접 실행하면 된다 (별도 파일 생성).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Windows 기본 콘솔(cp949)은 유니코드(— ≈ 등)를 못 찍어 UnicodeEncodeError를 낸다.
# 진단 print가 파이프라인을 죽이지 않도록 stdout/stderr를 utf-8로 재설정한다.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from investor_flow import build_investor_flow_html, load_investor_flow
from main import _load_dotenv, generate_fgi_section
from options_main import generate_options_sections
from options_report import EXTRA_STYLE
from outlook import build_outlook_section
from report import build_page_shell
from stock_options_main import generate_stock_options_sections

BASE_DIR = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "reports"
UPLOADS_DIR = BASE_DIR / "uploads"


def main() -> None:
    _load_dotenv(BASE_DIR / ".env")

    fgi_html, kospi_close, kospi200_close, total_score, fgi_facts = generate_fgi_section()
    option_sections, resolved_bas_dd_date, option_facts = generate_options_sections()
    stock_sections, stock_facts = generate_stock_options_sections(
        bas_dd=resolved_bas_dd_date.strftime("%Y%m%d") if resolved_bas_dd_date else None,
        as_of=resolved_bas_dd_date,
    )

    investor_flow = load_investor_flow(UPLOADS_DIR)

    today = date.today()
    tabs = [("fgi", "공포탐욕지수", fgi_html)]
    if option_sections:
        kospi_opt_html = "\n".join(option_sections)
        if investor_flow is not None:
            kospi_opt_html += build_investor_flow_html(investor_flow, options_as_of=resolved_bas_dd_date)
        tabs.append(("kospi-opt", "코스피200 옵션", kospi_opt_html))
    if stock_sections:
        tabs.append(("stock-opt", "삼성전자·SK하이닉스", "\n".join(stock_sections)))

    # 4번째 탭: 세 섹션 종합 + 내일 시나리오 (ANTHROPIC_API_KEY 없으면 None → 탭 생략)
    as_of_outlook = resolved_bas_dd_date or today
    outlook_html = build_outlook_section(as_of_outlook, fgi_facts, option_facts + stock_facts)
    if outlook_html:
        tabs.append(("outlook", "종합 전망", outlook_html))

    html = build_page_shell(
        report_date=today,
        kospi_close=kospi_close,
        kospi200_close=kospi200_close,
        extra_style=EXTRA_STYLE,
        tabs=tabs,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{today.isoformat()}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"통합 리포트 생성 완료: {out_path}")
    if total_score is not None:
        print(f"TOTAL KFGI: {total_score:.1f}")
    if not option_sections:
        print("코스피200 옵션 섹션: 데이터 없음 (건너뜀)")
    if not stock_sections:
        print("개별주식 옵션 섹션: 데이터 없음 (건너뜀)")
    if investor_flow is not None:
        print(f"투자자별 순매수(수동 업로드) 반영됨: {investor_flow['updated_at']:%Y-%m-%d %H:%M} 기준 파일")


if __name__ == "__main__":
    main()
