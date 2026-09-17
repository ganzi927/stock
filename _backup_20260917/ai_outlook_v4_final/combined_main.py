"""매일 실행 (운영용): KFGI + 코스피200 옵션 + 개별주식 옵션을 탭으로 구분된
하나의 HTML로 합쳐서 생성.

사용법:
    python combined_main.py                 # 최신 거래일(캐시 기준) 리포트
    python combined_main.py --as-of 2026-09-07   # 그 거래일 기준으로 (재)생성
    python combined_main.py --force              # 이미 완결된 리포트가 있어도 다시 생성

동작 원칙:
  - 리포트는 **하나의 거래일(anchor)** 에 완전히 고정된다. anchor = --as-of 이하의
    마지막 거래일(kospi200 캐시 기준). FGI·옵션·개별주식·헤더·종합전망 전부 그 날 마감.
  - **엄격 게이트**: anchor 당일 옵션 EOD가 KRX에 아직 없으면 리포트를 만들지 않고
    exit 3 으로 끝난다 (이전 거래일로 조용히 폴백하지 않음). 스케줄러가 나중에
    (07:30·부팅·저녁 슬롯) 다시 실행하면 그때 완성된다.
  - **멱등**: 같은 anchor 의 완결 리포트가 이미 있으면 AI 재호출 없이 즉시 종료.

run_daily.ps1 이 이 스크립트를 호출한다. 개별적으로 보고 싶으면 main.py /
options_main.py / stock_options_main.py를 각각 직접 실행하면 된다 (별도 파일 생성).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Windows 기본 콘솔(cp949)은 유니코드(— ≈ 등)를 못 찍어 UnicodeEncodeError를 낸다.
# 진단 print가 파이프라인을 죽이지 않도록 stdout/stderr를 utf-8로 재설정한다.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

from investor_flow import build_investor_flow_html, load_investor_flow
from main import _load_dotenv, generate_fgi_section
from naver_data import fetch_index_history, update_cache
from options_data import REGULAR_PROD, fetch_option_chain
from options_main import generate_options_sections
from options_report import EXTRA_STYLE
from outlook import build_outlook_section
from report import build_page_shell
from stock_options_main import generate_stock_options_sections

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"
REPORTS_DIR = BASE_DIR / "reports"
UPLOADS_DIR = BASE_DIR / "uploads"

EXIT_OK = 0
EXIT_NO_PRICE = 2      # anchor를 잡을 시세 자체가 캐시에 없음
EXIT_OPTIONS_PENDING = 3  # anchor 당일 옵션 EOD 미게시 — 나중에 재시도
REPORT_CONTRACT_VERSION = 4


def _resolve_anchor(kospi200: pd.DataFrame, as_of_req: date) -> date | None:
    prior = kospi200[pd.to_datetime(kospi200["date"]).dt.date <= as_of_req]
    if prior.empty:
        return None
    return prior.iloc[-1]["date"].date()


def _read_meta(meta_path: Path) -> dict:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _bump_pending(pending_path: Path) -> int:
    """anchor 옵션이 아직 없을 때 시도 횟수를 기록(관측용). 반환: 누적 시도 수."""
    data = _read_meta(pending_path)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    data["attempts"] = int(data.get("attempts", 0)) + 1
    data.setdefault("first_seen", now)
    data["last_attempt"] = now
    try:
        pending_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return data["attempts"]


def _report_is_current(meta: dict) -> bool:
    from data_quality import POLICY_VERSION
    return (bool(meta.get("options_complete"))
            and meta.get("quality_policy_version") == POLICY_VERSION
            and meta.get("report_contract_version") == REPORT_CONTRACT_VERSION)


def main() -> None:
    ap = argparse.ArgumentParser(description="KFGI + 옵션 통합 리포트 생성")
    ap.add_argument(
        "--as-of",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=date.today(),
        help="기준일(YYYY-MM-DD). 이 날짜 이하 마지막 거래일로 고정. 기본: 오늘",
    )
    ap.add_argument("--force", action="store_true", help="완결 리포트가 있어도 다시 생성")
    args = ap.parse_args()

    _load_dotenv(BASE_DIR / ".env")

    # anchor 결정 — --as-of 이하 마지막 거래일 (kospi200 캐시 기준, 900일 확보)
    kospi200 = update_cache(CACHE_DIR / "kospi200.csv", fetch_index_history, "KPI200", min_days=900)
    anchor = _resolve_anchor(kospi200, args.as_of)
    if anchor is None:
        print(f"기준일 {args.as_of} 이하의 시세가 캐시에 없습니다.")
        sys.exit(EXIT_NO_PRICE)

    out_path = REPORTS_DIR / f"{anchor.isoformat()}.html"
    meta_path = REPORTS_DIR / f"{anchor.isoformat()}.meta.json"
    pending_path = REPORTS_DIR / f"{anchor.isoformat()}.pending.json"

    # 멱등 가드: 같은 anchor의 완결 리포트가 이미 있으면 아무것도 안 한다(AI 재호출 방지).
    if not args.force and out_path.exists() and _report_is_current(_read_meta(meta_path)):
        print(f"이미 완결된 리포트가 있습니다: {out_path}  (재생성하려면 --force)")
        sys.exit(EXIT_OK)

    # 엄격 게이트: anchor 당일 옵션 EOD(정규월물)가 KRX에 있어야만 생성.
    if fetch_option_chain(anchor.strftime("%Y%m%d"), REGULAR_PROD).empty:
        n = _bump_pending(pending_path)
        print(
            f"옵션 EOD 미게시 (기준일 {anchor}, 누적 시도 {n}회). 리포트를 생성하지 않습니다 "
            f"— 다음 스케줄(07:30·부팅·저녁 슬롯)에 재시도합니다."
        )
        sys.exit(EXIT_OPTIONS_PENDING)

    # ---------------- 완전 생성 ----------------
    # 옵션 섹션을 먼저 만든다 — 여기서 실패하면(엄격 게이트를 통과했는데도) 리포트를
    # 아예 쓰지 않고 재시도로 넘긴다("옵션 없는 반쪽 리포트" 금지).
    option_sections, opt_bas_dd, opt_exact, option_facts = generate_options_sections(
        kospi200=kospi200, as_of=anchor, require_exact=True
    )
    if not option_sections or not opt_exact or opt_bas_dd != anchor:
        n = _bump_pending(pending_path)
        print(
            f"옵션 섹션 생성 실패/불일치 (기준일 {anchor}, opt_bas_dd={opt_bas_dd}, "
            f"누적 시도 {n}회). 리포트를 생성하지 않고 재시도로 넘깁니다."
        )
        sys.exit(EXIT_OPTIONS_PENDING)

    fgi_html, kospi_close, kospi200_close, total_score, fgi_facts, fgi_as_of = generate_fgi_section(as_of=anchor)
    stock_sections, stock_facts = generate_stock_options_sections(
        bas_dd=anchor.strftime("%Y%m%d"),
        as_of=anchor,
    )

    investor_flow = load_investor_flow(UPLOADS_DIR)

    tabs = [("fgi", "공포탐욕지수", fgi_html)]
    if option_sections:
        kospi_opt_html = "\n".join(option_sections)
        if investor_flow is not None:
            kospi_opt_html += build_investor_flow_html(investor_flow, options_as_of=anchor)
        tabs.append(("kospi-opt", "코스피200 옵션", kospi_opt_html))
    if stock_sections:
        tabs.append(("stock-opt", "삼성전자·SK하이닉스", "\n".join(stock_sections)))

    # 4번째 탭: 기준일 관측 사실의 결정론적 종합 (LLM 호출 없음)
    outlook_html = build_outlook_section(anchor, fgi_facts, option_facts + stock_facts)
    if outlook_html:
        tabs.append(("outlook", "종합 상태", outlook_html))

    html = build_page_shell(
        report_date=anchor,
        kospi_close=kospi_close,
        kospi200_close=kospi200_close,
        extra_style=EXTRA_STYLE,
        tabs=tabs,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    from data_quality import POLICY_VERSION
    meta = {
        "quality_policy_version": POLICY_VERSION,
        "report_contract_version": REPORT_CONTRACT_VERSION,
        "quality": {"fgi": (fgi_facts or {}).get("quality", {}), "options": [{"title": f["title"], "quality": f["quality"]} for f in option_facts + stock_facts]},
        "anchor": anchor.isoformat(),
        "fgi_as_of": fgi_as_of.isoformat() if fgi_as_of else None,
        "option_bas_dd": opt_bas_dd.isoformat() if opt_bas_dd else None,
        "options_complete": True,
        "has_stock_options": bool(stock_sections),
        "has_outlook": bool(outlook_html),
        "total_kfgi": total_score,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "attempts": _read_meta(pending_path).get("attempts", 0) + 1,
        "as_of_requested": args.as_of.isoformat(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    pending_path.unlink(missing_ok=True)

    print(f"통합 리포트 생성 완료: {out_path}  (기준일 {anchor})")
    if total_score is not None:
        print(f"TOTAL KFGI: {total_score:.1f}")
    if fgi_as_of and fgi_as_of != anchor:
        print(f"⚠ FGI 탭 기준일이 {fgi_as_of} 로 anchor({anchor})와 다릅니다 (시세 캐시 지연 가능).")
    if not stock_sections:
        print("개별주식 옵션 섹션: 데이터 없음 (건너뜀)")
    if investor_flow is not None:
        print(f"투자자별 순매수(수동 업로드) 반영됨: {investor_flow['updated_at']:%Y-%m-%d %H:%M} 기준 파일")

    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
