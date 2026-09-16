"""KB증권에서 수동으로 다운로드한 '상장일 누적 옵션 투자자별 순매수' 엑셀을 읽어
실제 투자자 유형별(개인/외국인/금융투자/투신) 콜·풋 순매수를 리포트에 참고용으로 표시한다.

이 데이터는 무료 KRX Open API 서비스 목록에 없어 자동 수집이 불가능하다 (KRX Open API
공식 서비스 목록 확인 완료 — 파생상품 카테고리엔 '일별매매정보'만 있고 투자자유형별
데이터는 없음). 그래서 사용자가 uploads/ 폴더에 파일을 넣어줄 때만 반영되는 수동 기능이다.
파일이 없으면 조용히 건너뛴다.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from charts import INK, MUTED, _fig_to_base64, _style_axes

INVESTOR_TYPES = ["금융투자", "개인", "외국인", "투신"]


def _parse_num(x) -> float | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class InvestorFlowTotals:
    call: dict[str, float]
    put: dict[str, float]


@dataclass
class _Layout:
    df: pd.DataFrame
    header_row_idx: int
    strike_col: int
    idx_col: int
    call_cols: dict[str, int]
    put_cols: dict[str, int]
    total_row_idx: int | None


def _locate_layout(path: Path) -> _Layout | None:
    df = pd.ExcelFile(path).parse("Document", header=None)

    # 0행은 "콜옵션 추정내역(...)" 같은 병합-타이틀 행이라 "행사가"가 거기도 나타날 수 있다.
    # 실제 투자자 라벨("금융투자")이 있는 행을 헤더로 삼는다.
    header_row_idx = None
    strike_col = None
    for i in range(min(5, len(df))):
        row = df.iloc[i]
        if (row == "금융투자").any():
            matches = row[row == "행사가"]
            if not matches.empty:
                header_row_idx = i
                strike_col = matches.index[0]
                break
    if header_row_idx is None or strike_col is None:
        return None
    idx_col = strike_col + 1
    header = df.iloc[header_row_idx]

    call_cols = {header[c]: c for c in range(0, strike_col) if header[c] in INVESTOR_TYPES}
    put_cols = {header[c]: c for c in range(idx_col + 1, df.shape[1]) if header[c] in INVESTOR_TYPES}

    total_row_idx = None
    for i in range(header_row_idx + 1, len(df)):
        if str(df.iat[i, idx_col]).strip() == "합계":
            total_row_idx = i
            break

    return _Layout(df, header_row_idx, strike_col, idx_col, call_cols, put_cols, total_row_idx)


def _parse_totals(path: Path) -> InvestorFlowTotals | None:
    layout = _locate_layout(path)
    if layout is None or layout.total_row_idx is None:
        return None
    total_row = layout.df.iloc[layout.total_row_idx]

    call = {name: v for name, col in layout.call_cols.items() if (v := _parse_num(total_row[col])) is not None}
    put = {name: v for name, col in layout.put_cols.items() if (v := _parse_num(total_row[col])) is not None}
    if not call and not put:
        return None
    return InvestorFlowTotals(call=call, put=put)


def _parse_per_strike(path: Path, investor: str) -> tuple[dict[float, float], dict[float, float]] | None:
    """행사가별 특정 투자자 유형(예: '금융투자', '외국인') 콜/풋 순매수를 {행사가: 값}로 반환."""
    layout = _locate_layout(path)
    if layout is None or investor not in layout.call_cols or investor not in layout.put_cols:
        return None
    call_col = layout.call_cols[investor]
    put_col = layout.put_cols[investor]

    end = layout.total_row_idx if layout.total_row_idx is not None else len(layout.df)
    call: dict[float, float] = {}
    put: dict[float, float] = {}
    for i in range(layout.header_row_idx + 1, end):
        strike = _parse_num(layout.df.iat[i, layout.strike_col])
        if strike is None:
            continue
        strike = round(strike, 1)
        cv = _parse_num(layout.df.iat[i, call_col])
        if cv is not None:
            call[strike] = cv
        pv = _parse_num(layout.df.iat[i, put_col])
        if pv is not None:
            put[strike] = pv
    return call, put


def build_strike_sign_overrides(upload_dir: Path) -> dict[tuple[float, str], int] | None:
    """행사가별 '금융투자' 순매수 부호를 (행사가, C/P) -> +1/-1 로 반환.

    금액 파일과 수량 파일 둘 다에서 부호가 일치하는 행사가만 채택한다(노이즈 방지) —
    둘 중 하나가 없거나 부호가 엇갈리면 그 행사가는 override에서 빠지고, 호출하는 쪽이
    기존 업계 표준 가정으로 대체한다.
    """
    amount_files = sorted(glob.glob(str(upload_dir / "*순매수_금액*.xlsx")), key=lambda p: Path(p).stat().st_mtime)
    qty_files = sorted(glob.glob(str(upload_dir / "*순매수_수량*.xlsx")), key=lambda p: Path(p).stat().st_mtime)
    if not amount_files or not qty_files:
        return None

    amount = _parse_per_strike(Path(amount_files[-1]), "금융투자")
    qty = _parse_per_strike(Path(qty_files[-1]), "금융투자")
    if amount is None or qty is None:
        return None
    amount_call, amount_put = amount
    qty_call, qty_put = qty

    overrides: dict[tuple[float, str], int] = {}
    for opt_type, amt_map, qty_map in (("C", amount_call, qty_call), ("P", amount_put, qty_put)):
        for strike, a in amt_map.items():
            q = qty_map.get(strike)
            if q is None or a == 0 or q == 0:
                continue
            sign_a, sign_q = (1 if a > 0 else -1), (1 if q > 0 else -1)
            if sign_a == sign_q:
                overrides[(strike, opt_type)] = sign_a
    return overrides or None


def load_investor_flow(upload_dir: Path) -> dict | None:
    """upload_dir(uploads/)에서 KB증권 '순매수_금액'/'순매수_수량' 파일을 찾아 파싱한다.
    둘 다 없으면 None (조용히 건너뜀)."""
    amount_files = sorted(glob.glob(str(upload_dir / "*순매수_금액*.xlsx")), key=lambda p: Path(p).stat().st_mtime)
    qty_files = sorted(glob.glob(str(upload_dir / "*순매수_수량*.xlsx")), key=lambda p: Path(p).stat().st_mtime)
    if not amount_files and not qty_files:
        return None

    amount = _parse_totals(Path(amount_files[-1])) if amount_files else None
    qty = _parse_totals(Path(qty_files[-1])) if qty_files else None
    if amount is None and qty is None:
        return None

    foreign_per_strike = _parse_per_strike(Path(amount_files[-1]), "외국인") if amount_files else None

    mtimes = [Path(p).stat().st_mtime for p in (amount_files[-1:] + qty_files[-1:])]
    updated_at = datetime.fromtimestamp(max(mtimes))
    return {"amount": amount, "qty": qty, "updated_at": updated_at, "foreign_per_strike": foreign_per_strike}


def _fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "-"
    return f"{v:+,.0f}{unit}"


def foreign_distribution_chart(call_map: dict[float, float], put_map: dict[float, float]) -> str | None:
    """행사가별 외국인 콜/풋 순매수(금액) 분포 막대 차트. 데이터가 없으면 None."""
    strikes = sorted(set(call_map) | set(put_map))
    if not strikes:
        return None
    call_vals = [call_map.get(s, 0.0) for s in strikes]
    put_vals = [put_map.get(s, 0.0) for s in strikes]

    fig, ax = plt.subplots(figsize=(9, 3.8))
    width = (strikes[1] - strikes[0]) * 0.35 if len(strikes) > 1 else 1.0
    ax.bar([s - width / 2 for s in strikes], call_vals, width=width, color="#6B7A8F", label="콜 순매수")
    ax.bar([s + width / 2 for s in strikes], put_vals, width=width, color="#B58A4A", label="풋 순매수")
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_title("외국인 행사가별 순매수 분포 (백만원)", fontsize=11, loc="left", color=INK)
    ax.set_xlabel("행사가", fontsize=9, color=MUTED)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    _style_axes(ax)
    fig.tight_layout()
    return _fig_to_base64(fig)


def _foreign_key_points(call_map: dict[float, float], put_map: dict[float, float]) -> list[str]:
    """외국인 행사가별 분포에서 눈여겨볼 지점을 문장으로 요약 — 최대 순매수/순매도
    행사가만 뽑는 사실 서술이며, 방향 예측이나 조언은 아니다."""
    points: list[str] = []
    if call_map:
        top_buy = max(call_map.items(), key=lambda kv: kv[1])
        top_sell = min(call_map.items(), key=lambda kv: kv[1])
        if top_buy[1] > 0:
            points.append(f"콜옵션 최대 순매수 행사가: {top_buy[0]:,.1f} ({top_buy[1]:+,.0f}백만원)")
        if top_sell[1] < 0:
            points.append(f"콜옵션 최대 순매도 행사가: {top_sell[0]:,.1f} ({top_sell[1]:+,.0f}백만원)")
    if put_map:
        top_buy = max(put_map.items(), key=lambda kv: kv[1])
        top_sell = min(put_map.items(), key=lambda kv: kv[1])
        if top_buy[1] > 0:
            points.append(f"풋옵션 최대 순매수 행사가: {top_buy[0]:,.1f} ({top_buy[1]:+,.0f}백만원)")
        if top_sell[1] < 0:
            points.append(f"풋옵션 최대 순매도 행사가: {top_sell[0]:,.1f} ({top_sell[1]:+,.0f}백만원)")
    return points


def build_investor_flow_html(data: dict, options_as_of: date | None = None) -> str:
    amount: InvestorFlowTotals | None = data["amount"]
    qty: InvestorFlowTotals | None = data["qty"]
    updated_at: datetime = data["updated_at"]
    foreign_per_strike = data.get("foreign_per_strike")

    rows = ""
    for investor in INVESTOR_TYPES:
        call_amt = amount.call.get(investor) if amount else None
        put_amt = amount.put.get(investor) if amount else None
        call_qty = qty.call.get(investor) if qty else None
        put_qty = qty.put.get(investor) if qty else None

        def _cls(v: float | None) -> str:
            if v is None:
                return ""
            return "color:#3D5C36" if v >= 0 else "color:#8A4A47"

        rows += (
            f"<tr><td>{investor}</td>"
            f"<td class='num' style='{_cls(call_amt)}'>{_fmt(call_amt, '백만원')}</td>"
            f"<td class='num' style='{_cls(put_amt)}'>{_fmt(put_amt, '백만원')}</td>"
            f"<td class='num' style='{_cls(call_qty)}'>{_fmt(call_qty, '계약')}</td>"
            f"<td class='num' style='{_cls(put_qty)}'>{_fmt(put_qty, '계약')}</td></tr>"
        )

    geumtu_call = amount.call.get("금융투자") if amount else None
    geumtu_put = amount.put.get("금융투자") if amount else None
    note = ""
    if geumtu_call is not None and geumtu_put is not None:
        direction = "순매수" if geumtu_call >= 0 and geumtu_put >= 0 else ("순매도" if geumtu_call < 0 and geumtu_put < 0 else "방향 혼재")
        note = (
            f"금융투자는 콜·풋 모두 {direction}입니다. 다만 이 수치를 GEX/DEX의 '딜러 방향' 가정을 "
            f"검증하는 근거로 쓸 수는 없습니다 — '금융투자'는 마켓메이킹뿐 아니라 ELS 헤지·자기매매·랩운용까지 "
            f"포함하는 광범위한 분류라 실제 옵션 마켓메이커 인벤토리와 다르고, 애초에 딜러의 실제 방향성 "
            f"포지션은 미국 시장(SpotGamma의 DDOI)조차 \"공개되지도 상업적으로 구매 가능하지도 않은\" 비공개 "
            f"정보라 어느 시장에서도 실측 검증이 불가능합니다. 그래서 이 표는 GEX/DEX 가정의 참/거짓을 "
            f"가리는 근거가 아니라, 단순히 '이런 실제 매매 동향도 있다'는 별개의 참고 정보입니다."
        )

    date_mismatch_html = ""
    if options_as_of is not None and updated_at.date() != options_as_of:
        when = "오늘 장중" if updated_at.date() == date.today() else updated_at.strftime("%Y-%m-%d")
        date_mismatch_html = (
            f'<div class="warn-banner">⚠ 기준 시점이 다릅니다 — 위 옵션 분석(정규월물/위클리)은 '
            f"<b>{options_as_of.isoformat()} 종가</b> 기준인데, 이 KB증권 파일은 "
            f'<b>{updated_at.strftime("%Y-%m-%d %H:%M")}({when}) 스냅샷</b>입니다. '
            f"옵션 EOD 데이터 게시 지연 때문에 위 옵션 분석은 하루 전 종가를 쓰는 반면, 이 파일은 "
            f"사용자가 업로드한 시점(장중일 수 있음) 기준입니다. 서로 다른 시점 데이터이니 "
            f"위 레벨과 직접 비교하지 마세요.</div>"
        )

    chart_html = ""
    if foreign_per_strike is not None:
        call_map, put_map = foreign_per_strike
        img = foreign_distribution_chart(call_map, put_map)
        if img:
            points = _foreign_key_points(call_map, put_map)
            points_html = "".join(f"<li>{p}</li>" for p in points)
            chart_html = f"""
      <h3 style="font-size:14px;font-weight:500;margin:20px 0 8px">외국인 행사가별 분포 <span style="color:var(--muted);font-weight:400;font-size:12px">— 클릭하면 크게 보기</span></h3>
      <div class="chart-zoomable">
        <input type="checkbox" id="modal-foreign-dist" class="modal-toggle">
        <label for="modal-foreign-dist" class="chart-zoom-trigger">
          <img src="data:image/png;base64,{img}" style="width:100%"/>
          <div class="zoom-hint">🔍 클릭해서 크게 보기</div>
        </label>
        <div class="modal-overlay">
          <label for="modal-foreign-dist" class="modal-backdrop"></label>
          <div class="modal-content">
            <label for="modal-foreign-dist" class="modal-close">✕</label>
            <img src="data:image/png;base64,{img}"/>
          </div>
        </div>
      </div>
      <ul class="key-points">{points_html}</ul>"""

    return f"""
    <div class="section-block">
      <h2>실제 투자자별 순매수 (참고용) <span style="color:var(--muted);font-weight:400;font-size:14px">— KB증권 수동 업로드, {updated_at.strftime('%Y-%m-%d %H:%M')} 기준 파일, 상장일 누적</span></h2>
      <div class="warn-banner">⚠ 사용자가 KB증권에서 직접 다운로드해 uploads/ 폴더에 넣은 파일을 그대로 반영했습니다.
      무료 API로 자동 수집이 불가능해(KRX Open API 파생상품 카테고리에 투자자유형별 데이터 없음) 파일을
      새로 넣어줄 때만 갱신됩니다. 어느 옵션 시리즈(정규월물/위클리) 기준인지는 파일에 명시되어 있지 않습니다.</div>
      {date_mismatch_html}
      <table class="level-table">
        <tr><th>투자자</th><th>콜 순매수(금액)</th><th>풋 순매수(금액)</th><th>콜 순매수(수량)</th><th>풋 순매수(수량)</th></tr>
        {rows}
      </table>
      {f'<div class="scenario-row" style="margin-top:12px">{note}</div>' if note else ''}
      {chart_html}
    </div>
    """
