"""Offline data readiness audit. No fetching, trading, or invented publication timestamps."""
import argparse
from datetime import date, datetime
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from data_quality import POLICY_VERSION
from reference_data import load_records

SOURCES={
 'kospi200.csv':(['close'],'네이버 KOSPI200'),
 'vkospi.csv':(['vkospi'],'KRX VKOSPI'),
 'putcall.csv':(['putcall'],'KRX 옵션 거래량'),
 'market_kospi.csv':(['close','trdvol','mktcap'],'KRX 전종목'),
 'bond10y_yield.csv':(['ktb10_yield'],'ECOS 국고채10년'),
 'credit_spread.csv':(['spread'],'ECOS 회사채'),
}


def inspect_cache(cache, as_of):
    result={}
    for name,(columns,source) in SOURCES.items():
        p=Path(cache)/name
        row=dict(source=source,path=str(p),as_of=as_of.isoformat(),available_at=None,
                 backtest_eligible=False,reason='원자료 공개시각·수정 이력 미확인')
        result[name]=row
        if not p.exists():
            row.update(status='missing',errors=['캐시 없음']);continue
        row['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        try:
            d=pd.read_csv(p)
            required=['date']+columns
            if any(c not in d for c in required): raise ValueError('필수 컬럼 누락')
            d['date']=pd.to_datetime(d['date'],errors='raise')
            keys=['date','ISU_CD'] if 'ISU_CD' in d else ['date']
            row['duplicate_rows']=int(d.duplicated(keys).sum())
            row['future_rows_excluded']=int((d.date.dt.date>as_of).sum())
            past=d[d.date.dt.date<=as_of]
            row['rows_asof']=len(past)
            row['latest_date']=past.date.max().date().isoformat() if len(past) else None
            bad={c:int((~np.isfinite(pd.to_numeric(past[c],errors='coerce'))).sum()) for c in columns}
            row['nonfinite_counts']=bad
            errors=[]
            if row['duplicate_rows']: errors.append('중복 키')
            if any(bad.values()): errors.append('결측/비유한 값')
            row['status']='invalid' if errors else 'missing' if past.empty else 'stale' if row['latest_date']!=as_of.isoformat() else 'observed'
            row['errors']=errors
        except (ValueError,KeyError,TypeError,pd.errors.ParserError) as exc:
            row.update(status='invalid',errors=[str(exc)])
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cache',type=Path,default=Path(__file__).with_name('cache'))
    ap.add_argument('--as-of',required=True,type=date.fromisoformat)
    ap.add_argument('--out',type=Path,default=Path(__file__).with_name('reports')/'input-quality.json')
    args=ap.parse_args()
    refs,errors=load_records()
    report=dict(policy_version=POLICY_VERSION,generated_at=datetime.now().astimezone().isoformat(),
                sources=inspect_cache(args.cache,args.as_of),reference_errors=errors,
                reference_counts={k:len(refs.get(k,[])) for k in ('expiries','dividends','dividend_coverage')},
                strategy_validated=False)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(args.out)
    return 0 if all(s['status']=='observed' for s in report['sources'].values()) and not errors else 2

if __name__=='__main__':
    raise SystemExit(main())
