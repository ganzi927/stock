"""Point-in-time reference records. Source URLs document provenance, not automatic verification."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlparse
import json

PATH = Path(__file__).with_name('reference_data.json')
OFFICIAL_HOSTS = ('krx.co.kr', 'dart.fss.or.kr', 'opendart.fss.or.kr', 'samsung.com', 'skhynix.com', 'sec.gov')


def cutoff(as_of):
    return datetime.combine(as_of, time.max, ZoneInfo('Asia/Seoul'))


def _valid_provenance(row, as_of):
    try:
        url = urlparse(row['source'])
        host = url.hostname or ''
        official = url.scheme == 'https' and any(host == h or host.endswith('.'+h) for h in OFFICIAL_HOSTS)
        known = datetime.fromisoformat(row['available_at'])
        return official and bool(row.get('verification_note')) and known.tzinfo is not None and known <= cutoff(as_of)
    except (KeyError, TypeError, ValueError):
        return False


def load_records(path=None):
    p = Path(path) if path is not None else PATH
    if not p.exists():
        return {}, ['공식 기준자료 파일 없음']
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        if data.get('schema_version') != 1:
            raise ValueError('schema_version must be 1')
        for key in ('expiries', 'dividends', 'dividend_coverage'):
            if not isinstance(data.get(key), list):
                raise ValueError(key + ' must be a list')
        return data, []
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {}, ['공식 기준자료 형식 오류: '+type(exc).__name__]


def resolve_expiry(product, nominal, as_of, path=None):
    data, errors = load_records(path)
    matches = []
    for row in data.get('expiries', []):
        if not isinstance(row, dict) or row.get('product') != product or row.get('nominal_expiry') != nominal.isoformat():
            continue
        if _valid_provenance(row, as_of):
            try:
                matches.append((date.fromisoformat(row['expiry']), row))
            except (ValueError, KeyError, TypeError):
                continue
    if matches:
        latest = max(matches, key=lambda pair: datetime.fromisoformat(pair[1]['available_at']))
        return latest[0], dict(kind='observed', source=latest[1]['source'], available_at=latest[1]['available_at'], reasons=[])
    return nominal, dict(kind='estimated', source='요일 계산(명목 만기)', available_at=None,
                         reasons=errors+['공식 최종거래일 미확인; 휴장일 보정 미확인'])


def dividend_schedule(name, start, end, path=None):
    data, errors = load_records(path)
    valid, reasons = [], list(errors)
    for row in data.get('dividends', []):
        if not isinstance(row, dict) or row.get('name') != name or not _valid_provenance(row, start):
            continue
        try:
            ex = date.fromisoformat(row['ex_date']); pay = date.fromisoformat(row['pay_date'])
            amount = float(row['amount'])
            if not (amount >= 0 and amount < float('inf') and pay >= ex):
                raise ValueError('invalid dividend')
            if start < ex <= end:
                valid.append(dict(row, ex_date=ex, pay_date=pay, amount=amount))
        except (ValueError, KeyError, TypeError):
            reasons.append('배당 레코드 형식 오류')
    # A completeness attestation must also have been known at the historical cutoff.
    complete = False
    for row in data.get('dividend_coverage', []):
        if not isinstance(row, dict) or row.get('name') != name or row.get('complete') is not True or not _valid_provenance(row, start):
            continue
        try:
            complete |= date.fromisoformat(row['start']) <= start and date.fromisoformat(row['end']) >= end
        except (ValueError, KeyError, TypeError):
            reasons.append('배당 커버리지 형식 오류')
    # Revised events must use one stable event_id; latest known record wins.
    events = {}
    for row in sorted(valid, key=lambda r: datetime.fromisoformat(r['available_at'])):
        key = row.get('event_id')
        if not key:
            reasons.append('배당 event_id 누락'); continue
        events[key] = row
    if not complete:
        reasons.append('만기 내 배당 일정 완전성 미확인; 누락을 배당 0으로 해석하지 않음')
    return list(events.values()), complete and not reasons, reasons


def apply_expiry_evidence(df, product, as_of):
    if df.empty:
        return df
    df=df.copy()
    df['nominal_expiry']=df['expiry']
    for nominal in df.nominal_expiry.unique():
        actual,evidence=resolve_expiry(product,nominal,as_of)
        mask=df.nominal_expiry==nominal
        df.loc[mask,'expiry']=actual
        df.loc[mask,'expiry_kind']=evidence['kind']
        df.loc[mask,'expiry_source']=evidence['source']
        df.loc[mask,'expiry_available_at']=evidence['available_at']
    return df
