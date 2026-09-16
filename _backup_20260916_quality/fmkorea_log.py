"""fmkorea "오늘의 코스피" 시리즈 수치 로깅 — 실험적, 폐기 가능.

곰곰이곰곰(회원번호 5493236506)의 "정보공유" 글 목록을 페이지 단위로 훑어
"오늘의 코스피 - ..." 글의 핵심 수치를 `cache/fmkorea_log.csv`에 증분 저장한다.

목적: 우리 리포트의 Credit Spread / Strength 정규화 창을 fmkorea 시계열 대비
tracking-error로 보정할 데이터 확보 (RECONCILIATION.md §4 B그룹).

**combined_main.py와 완전히 분리돼 있다** — 이 파일과 `cache/fmkorea_log.csv`만
지우면 흔적 없이 원복된다. 아이디어가 폐기되면 그냥 삭제하면 됨.

**타이밍 무관 — 따라잡기(catch-up) 방식.** 작성자가 몇 시에 글을 올리는지 알 필요 없다.
돌릴 때마다 이미 저장된 글 번호(seen)와 대조해 "그때까지 올라온 새 글"만 받는다. 실행
뒤에 글이 올라왔으면 그날치는 다음 실행 때 들어온다(하루 늦을 뿐 유실 없음). 정규화 창
튜닝용 과거 시계열 수집이 목적이라 최근 점이 하루 늦어도 상관없다. 월 1회 수동 실행이면
충분하고, 유일한 리스크는 fmkorea가 오래된 글을 지우는 것 → 되도록 빨리 한 번 전체 백필.

**주의: 2026-07-06 이전 글은 지표 수치가 이미지로만** 들어 있어 텍스트 파싱이 안 된다
(본문은 `[시장 강도]` 같은 캡션뿐). 그런 글은 parse_ok=0으로 CSV에 남되(재fetch 방지),
분석에선 parse_ok=1만 쓰면 된다. 그 이전까지 필요하면 dashboard 이미지 vision/OCR이 필요.

사용:
    python fmkorea_log.py                # 증분 갱신 (이미 저장된 글 만나면 중단)
    python fmkorea_log.py --backfill     # 끝까지 백필 (최초 1회)
    python fmkorea_log.py --pages 15     # 최대 N페이지
    python fmkorea_log.py --fgi-only     # 공포탐욕지수편만 (Credit Spread/Strength 보정엔 이것만 필요)
    python fmkorea_log.py --delay 3.0    # 요청 간 딜레이(초), 기본 2.5
    python fmkorea_log.py --llm          # 정규식 실패분을 Haiku로 재추출 (양식이 매일 바뀜)
    python fmkorea_log.py --reparse --llm  # 재크롤 없이 저장된 text 재파싱

주의: fmkorea는 공격적 스크래핑을 차단한다. 딜레이를 줄이지 말 것. plain requests가
막히면(403/429/빈 응답) --via-browser 안내 메시지가 뜬다 — 그 경우 Claude-in-Chrome
같은 실제 브라우저 세션으로 목록/본문을 받아 같은 파서에 넣으면 된다.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

# Windows 콘솔(cp949)에서 em-dash 등으로 print가 깨지지 않게.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "https://www.fmkorea.com"
MEMBER_SRL = "5493236506"       # 곰곰이곰곰
CATEGORY_INFO = "196633079"     # 정보공유 탭
BASE_DIR = Path(__file__).parent
LOG_CSV = BASE_DIR / "cache" / "fmkorea_log.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CSV_FIELDS = ["date", "post_type", "document_srl", "title", "url", "fetched_at", "parse_ok", "payload", "text"]

# ---------------------------------------------------------------------------
# 글 종류 판별 (제목 기준)
# ---------------------------------------------------------------------------
_TITLE_DATE_RE = re.compile(r"\((\d{1,2})\s*월\s*(\d{1,2})\s*일\)")


def classify(title: str) -> str | None:
    if "오늘의 코스피" not in title:
        return None
    if "공포탐욕" in title:
        return "fgi"
    if "삼성전자" in title or "삼전" in title or "하닉" in title or "SK하이닉스" in title:
        return "stock_options"
    if "옵션편" in title:
        return "options"
    return None


def title_to_date(title: str, seen_year: int) -> str | None:
    m = _TITLE_DATE_RE.search(title)
    if not m:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    # 시리즈는 2026-06 시작. 연말/연초 넘어가면 보정.
    year = seen_year
    today = date.today()
    if mm > today.month + 1:
        year -= 1
    try:
        return date(year, mm, dd).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 네트워크
# ---------------------------------------------------------------------------
class Blocked(RuntimeError):
    pass


_BLOCK_CODES = (403, 429, 430, 503)


def _get(session: requests.Session, url: str, params: dict | None = None, retries: int = 3) -> str:
    """차단 코드(403/429/430/503)나 빈 응답이면 지수 백오프로 재시도, 그래도 안 되면 Blocked."""
    wait = 20.0
    for attempt in range(retries + 1):
        r = session.get(url, params=params, headers=HEADERS, timeout=20)
        if r.status_code in _BLOCK_CODES or (r.status_code == 200 and len(r.text) < 500):
            if attempt < retries:
                print(f"  [{r.status_code}] 차단 감지, {wait:.0f}s 대기 후 재시도 ({attempt+1}/{retries})", file=sys.stderr)
                time.sleep(wait)
                wait *= 2
                continue
            raise Blocked(
                f"HTTP {r.status_code}, len={len(r.text)} - fmkorea IP 스로틀. "
                f"수십 분 뒤 재시도하거나(seen 목록으로 이어받음) 브라우저 경유 필요."
            )
        r.raise_for_status()
        return r.text
    raise Blocked("unreachable")


def list_page(session: requests.Session, page: int) -> list[dict]:
    """목록 한 페이지 → [{document_srl, title}]. XE 검색 결과 페이지에서 글 링크만 추출."""
    html = _get(
        session,
        f"{BASE}/index.php",
        {
            "mid": "stock",
            "search_target": "member_srl",
            "search_keyword": MEMBER_SRL,
            "category": CATEGORY_INFO,
            "listStyle": "list",
            "page": page,
        },
    )
    rows: list[dict] = []
    seen: set[str] = set()
    # <a href="....document_srl=NNN....">제목</a>  (댓글 링크 #..._comment 는 제외)
    for m in re.finditer(r'href="[^"]*?document_srl=(\d+)[^"]*?"[^>]*>([^<]{6,200})</a>', html):
        srl, title = m.group(1), m.group(2).strip()
        if srl in seen or "#" in m.group(0).split('"')[1]:
            continue
        if "오늘의 코스피" not in title:
            continue
        seen.add(srl)
        rows.append({"document_srl": srl, "title": re.sub(r"\s+", " ", title)})
    return rows


def fetch_post_text(session: requests.Session, document_srl: str) -> str:
    html = _get(session, f"{BASE}/{document_srl}")
    # 본문 article 영역만 대충 추출 후 태그 제거
    m = re.search(r"<article[^>]*>(.*?)</article>", html, flags=re.S)
    body = m.group(1) if m else html
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"</(p|div|tr|td|th|h[1-6]|li)>", "\n", body)
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# 파서
# ---------------------------------------------------------------------------
_NUM = r"[-+]?[\d,]+(?:\.\d+)?"

# fmkorea가 날마다 AI 리포트 양식을 바꾼다(표/줄바꿈/지표명이 다 다름). 지표명은
# 별칭 여러 개를 OR로 잡고, 공백을 전부 단일 스페이스로 뭉갠 뒤 "이름 다음의 숫자
# 2~3개"를 grab 하는 관대한 파서를 쓴다.
_FGI_ALIASES = {
    "momentum":     r"(?:Market\s+)?Momentum",
    "volatility":   r"Volatility(?:\s*\(VKOSPI\))?",
    "credit_spread": r"Credit\s+Spread",
    "strength":     r"(?:Market\s+)?Strength",
    "breadth":      r"(?:Stock\s+Price\s+)?Breadth",
    "putcall":      r"Put\s*/\s*Call(?:\s+Ratio)?",
    "safe_haven":   r"Safe\s+Haven(?:\s+Demand)?",
}


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def _num_suffix(tok: str) -> float:
    """'123.2M' / '13.4조' / '1.3억' 같은 접미사 숫자를 실수로."""
    tok = tok.replace(",", "").strip()
    mult = 1.0
    for suf, m in (("M", 1e6), ("B", 1e9), ("K", 1e3), ("조", 1e12), ("억", 1e8), ("만", 1e4)):
        if tok.endswith(suf):
            tok, mult = tok[: -len(suf)].strip(), m
            break
    try:
        return float(tok) * mult
    except ValueError:
        return float("nan")


def parse_fgi(text: str) -> dict:
    flat = re.sub(r"\s+", " ", text)
    out: dict = {"indicators": {}}

    # TOTAL 점수: fmkorea가 날마다 표현을 바꾼다 —
    #   "TOTAL FGI 47.4 (Neutral) 42.5 34.0 26.3"
    #   "(TOTAL FGI) 현재 점수 : 42.5 ( 중립 ... )"
    #   "현재 지수 값 (2026.08.24): 34.7 점 ( FEAR / 공포 )"
    #   "... 현재 (42.5)"  (1M/1W/1D 추세 줄 끝)
    m = re.search(rf"TOTAL FGI\s+({_NUM})\s*\(([^)]+)\)\s+({_NUM})\s+({_NUM})\s+({_NUM})", flat)
    if m:
        out.update(total=_f(m.group(1)), total_zone=m.group(2).strip(),
                   total_1d=_f(m.group(3)), total_1w=_f(m.group(4)), total_1m=_f(m.group(5)))
    else:
        for pat in (
            rf"현재\s*지수\s*값[^:：]*[:：]\s*({_NUM})",
            rf"현재\s*점수\s*[:：]\s*({_NUM})",
            rf"TOTAL FGI\)\s*[^.\d]*?({_NUM})",
            rf"현재\s*\(({_NUM})\)\s*(?:KOSPI|$)",
        ):
            m = re.search(pat, flat)
            if m:
                out["total"] = _f(m.group(1))
                break
    m = re.search(rf"1M\s*전?\s*\(({_NUM})\).*?1W\s*전?\s*\(({_NUM})\).*?1D\s*전?\s*\(({_NUM})\)", flat)
    if m:
        out.update(total_1m=_f(m.group(1)), total_1w=_f(m.group(2)), total_1d=_f(m.group(3)))

    m = re.search(rf"(?:KOSPI\s*200|종가 지수)\s*[:：]?\s*({_NUM})", flat)
    if m:
        out["kospi200"] = _f(m.group(1))
    m = re.search(rf"KOSPI 지수\s*[:：]?\s*({_NUM})", flat)
    if m:
        out["kospi"] = _f(m.group(1))

    for key, alias in _FGI_ALIASES.items():
        # 이름 뒤: raw(접미사 M/억/조 가능, 공백 있어도 됨) + score + [score_1d].
        mm = re.search(
            alias + r"\s+([-+]?[\d,]+(?:\.\d+)?)\s*([MBK조억만]?)\s+({n})(?:\s+({n}))?".format(n=_NUM),
            flat,
        )
        if not mm:
            continue
        rec = {"raw": _num_suffix(mm.group(1) + mm.group(2)), "score": _f(mm.group(3))}
        if mm.group(4):
            rec["score_1d"] = _f(mm.group(4))
        out["indicators"][key] = rec
    return out


def _grab_levels(text: str) -> dict:
    """옵션편/삼하편 공통: 'X.X 라벨' 또는 '라벨: X.X' 형태의 레벨을 최대한 긁는다."""
    d: dict = {}
    m = re.search(rf"Spot:\s*({_NUM})", text)
    if m:
        d["spot"] = _f(m.group(1))
    for label, keys in {
        "zero_gamma": ["Zero Gamma"],
        "gamma_wall": ["Gamma Wall"],
        "max_gamma": ["Max Gamma"],
        "max_pain": ["MaxPain", "Max Pain"],
        "dex_neutral": ["DEX 중립", "DEX Neutral"],
        "call_wall": ["Call Wall"],
        "put_wall": ["Put Wall"],
    }.items():
        for k in keys:
            m = re.search(rf"({_NUM})\s*(?:Pt|원)?\s*{re.escape(k)}", text) or re.search(rf"{re.escape(k)}\s*[:\-]?\s*({_NUM})", text)
            if m:
                d[label] = _f(m.group(1))
                break
    for label, k in {"skew_pct": r"쏠림도", "vanna_flow": r"Vanna Flow", "charm_flow": r"Charm Flow"}.items():
        m = re.search(rf"{k}\s*[:\-]?\s*(?:약\s*)?({_NUM})", text)
        if m:
            d[label] = _f(m.group(1))
    return d


def parse_options(text: str) -> dict:
    out = _grab_levels(text)
    m = re.search(r"기준일[:\s]*([\d.]+)", text)
    if m:
        out["basis_date_raw"] = m.group(1)
    return out


parse_stock_options = parse_options


PARSERS = {"fgi": parse_fgi, "options": parse_options, "stock_options": parse_stock_options}


# ---------------------------------------------------------------------------
# LLM 폴백 파서 (선택) — fmkorea가 AI 리포트 양식을 거의 매일 바꿔서 정규식만으론
# 절반 정도만 잡힌다. --llm 을 주면 정규식 실패분에 대해 Haiku로 숫자를 추출한다
# (ANTHROPIC_API_KEY 필요, 글당 약 $0.001).
# ---------------------------------------------------------------------------
def llm_extract_fgi(text: str) -> dict:
    import os
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "no ANTHROPIC_API_KEY"}
    prompt = (
        "다음은 한국 주식 커뮤니티의 '공포탐욕지수(KFGI)' 리포트 본문이다. "
        "아래 JSON 스키마로만 답하라(설명 금지, 코드펜스 금지). 값이 본문에 없으면 null.\n"
        '{"total": <숫자>, "total_zone": "<문자열>", '
        '"indicators": {"momentum": {"raw": <숫자>, "score": <숫자>}, '
        '"volatility": {...}, "credit_spread": {...}, "strength": {...}, '
        '"breadth": {...}, "putcall": {...}, "safe_haven": {...}}}\n'
        "score는 0~100 점수, raw는 원시값(모멘텀 1.0 근처, 스프레드 한 자리, breadth는 큰 수 또는 1.2e8 형태). "
        "지표명이 한글(모멘텀/변동성/신용스프레드/시장강도/시장넓이/풋콜비율/안전자산선호)로 나와도 위 영문 key에 매핑하라.\n\n"
        "=== 본문 ===\n" + text[:6000]
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 700,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=40,
        )
        r.raise_for_status()
        txt = "".join(p.get("text", "") for p in r.json().get("content", []) if p.get("type") == "text").strip()
        txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
        d = json.loads(txt)
        d["_via"] = "llm"
        return d
    except Exception as e:
        return {"error": f"llm: {e}"}


def _fgi_ok(payload: dict) -> bool:
    inds = payload.get("indicators", {})
    return sum(isinstance(v, dict) and v.get("score") is not None for v in inds.values()) >= 5 and {
        "credit_spread", "strength"
    } <= inds.keys()


def reparse_log(use_llm: bool) -> None:
    """cache/fmkorea_log.csv의 text 컬럼으로 payload/parse_ok를 재계산(재크롤 없음)."""
    if not LOG_CSV.exists():
        print("로그 없음."); return
    rows = list(csv.DictReader(LOG_CSV.open(encoding="utf-8")))
    changed = 0
    for r in rows:
        if not r.get("text"):
            continue
        payload = PARSERS[r["post_type"]](r["text"])
        ok = _fgi_ok(payload) if r["post_type"] == "fgi" else bool(payload.get("spot"))
        if not ok and use_llm and r["post_type"] == "fgi":
            llm = llm_extract_fgi(r["text"])
            if not llm.get("error"):
                payload, ok = llm, _fgi_ok(llm)
                time.sleep(1.0)
        new_payload = json.dumps(payload, ensure_ascii=False)
        if new_payload != r["payload"] or str(int(ok)) != r["parse_ok"]:
            r["payload"], r["parse_ok"], changed = new_payload, int(ok), changed + 1
    with LOG_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    okc = sum(r["parse_ok"] in (1, "1") for r in rows)
    print(f"재파싱: {changed}행 갱신. 현재 parse_ok {okc}/{len(rows)}")


# ---------------------------------------------------------------------------
# 로그 CSV I/O
# ---------------------------------------------------------------------------
def load_seen() -> set[str]:
    if not LOG_CSV.exists():
        return set()
    with LOG_CSV.open(encoding="utf-8", newline="") as f:
        return {row["document_srl"] for row in csv.DictReader(f)}


def append_rows(rows: list[dict]) -> None:
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG_CSV.exists()
    with LOG_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def run(max_pages: int, backfill: bool, fgi_only: bool, delay: float, use_llm: bool = False) -> int:
    seen = load_seen()
    print(f"이미 저장된 글 {len(seen)}개. {'백필' if backfill else '증분'} 모드, 최대 {max_pages}페이지, 딜레이 {delay}s")
    session = requests.Session()

    collected: list[dict] = []
    hit_known = False
    for page in range(1, max_pages + 1):
        try:
            entries = list_page(session, page)
        except Blocked as e:
            print(f"[차단] page {page}: {e}", file=sys.stderr)
            if collected:
                break
            print("\n한 글도 못 받았습니다. fmkorea가 plain requests를 막고 있습니다.", file=sys.stderr)
            print("→ Claude-in-Chrome 등 실제 브라우저로 목록/본문 텍스트를 받아 parse_fgi 등에 직접 넣으세요.", file=sys.stderr)
            return 2
        if not entries:
            print(f"page {page}: 항목 없음 — 끝으로 판단, 중단")
            break
        print(f"page {page}: '오늘의 코스피' {len(entries)}건")
        for e in entries:
            ptype = classify(e["title"])
            if ptype is None or (fgi_only and ptype != "fgi"):
                continue
            if e["document_srl"] in seen:
                hit_known = True
                if not backfill:
                    break
                continue
            e["post_type"] = ptype
            collected.append(e)
        if hit_known and not backfill:
            print("이미 저장된 글에 도달 — 증분 갱신 중단")
            break
        time.sleep(delay)

    print(f"\n새로 받을 글 {len(collected)}개. 본문 파싱 시작...")
    rows: list[dict] = []
    for i, e in enumerate(collected, 1):
        text = ""
        try:
            text = fetch_post_text(session, e["document_srl"])
            payload = PARSERS[e["post_type"]](text)
            ok = _fgi_ok(payload) if e["post_type"] == "fgi" else bool(payload.get("spot"))
            if not ok and use_llm and e["post_type"] == "fgi":
                llm = llm_extract_fgi(text)
                if not llm.get("error"):
                    payload, ok = llm, _fgi_ok(llm)
        except Blocked as ex:
            print(f"  [차단] {e['document_srl']}: {ex}", file=sys.stderr)
            break
        except Exception as ex:  # 파싱 실패는 건너뛰되 로그 (text 저장해두면 나중에 재파싱 가능)
            payload, ok = {"error": str(ex)}, False
        d = title_to_date(e["title"], seen_year=date.today().year)
        rows.append({
            "date": d or "",
            "post_type": e["post_type"],
            "document_srl": e["document_srl"],
            "title": e["title"],
            "url": f"{BASE}/{e['document_srl']}",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "parse_ok": int(ok),
            "payload": json.dumps(payload, ensure_ascii=False),
            "text": text[:5000],
        })
        flag = "ok" if ok else "PARSE?"
        print(f"  [{i}/{len(collected)}] {d} {e['post_type']:<14} {flag}")
        time.sleep(delay)

    if rows:
        append_rows(rows)
        print(f"\n{len(rows)}행 추가 → {LOG_CSV}")
    else:
        print("\n추가된 행 없음.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="끝까지 백필")
    ap.add_argument("--pages", type=int, default=4, help="최대 페이지 수 (기본 4, 백필 시 20)")
    ap.add_argument("--fgi-only", action="store_true", help="공포탐욕지수편만")
    ap.add_argument("--delay", type=float, default=2.5, help="요청 간 딜레이(초)")
    ap.add_argument("--llm", action="store_true", help="정규식 실패분을 Haiku로 재추출 (ANTHROPIC_API_KEY 필요)")
    ap.add_argument("--reparse", action="store_true", help="재크롤 없이 저장된 text로 payload만 다시 계산")
    args = ap.parse_args()
    if args.reparse:
        reparse_log(args.llm)
        sys.exit(0)
    pages = args.pages if not args.backfill else max(args.pages, 20)
    sys.exit(run(pages, args.backfill, args.fgi_only, args.delay, args.llm))
