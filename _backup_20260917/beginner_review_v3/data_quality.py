"""Explicit use boundaries for market context, research models and missing data."""
from dataclasses import asdict, dataclass, field
from datetime import date
import html
import math
import os
import numpy as np
import pandas as pd

POLICY_VERSION = 2

@dataclass
class Evidence:
    source: str
    as_of: str | None
    kind: str
    reasons: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    available_at: str | None = None

    def to_dict(self):
        return asdict(self)


def research_ai_enabled():
    return os.getenv('KFGI_RESEARCH_AI','0').lower() in ('1','true','yes','on')


def assess_series(df, as_of, source, estimated=False, dependencies=None, reason=None):
    dep = dependencies or []
    if df is None or df.empty:
        return Evidence(source,None,'missing',['입력 데이터 없음'],dep)
    s = df.copy(); s['date'] = pd.to_datetime(s['date'])
    s = s.loc[s['date'].dt.date <= as_of].sort_values('date')
    if s.empty:
        return Evidence(source,None,'missing',['기준일 이전 데이터 없음'],dep)
    last = s.iloc[-1]
    actual = last['date'].date()
    if actual != as_of:
        return Evidence(source,actual.isoformat(),'stale',['기준일과 입력 거래일 불일치'],dep)
    if 'raw' in s and not np.isfinite(last['raw']):
        return Evidence(source,actual.isoformat(),'missing',['기준일 원자료 결측'],dep)
    return Evidence(source,actual.isoformat(),'estimated' if estimated else 'observed',
                    [reason or '미검증 대체 모형'] if estimated else [],dep)


def option_quality(chain, spot, as_of, r_source, q_source):
    source = 'KRX Open API 옵션 일별매매정보'
    chain=chain.copy()
    fatal=[]
    required={'strike','type','oi','volume','iv','expiry'}
    if not required.issubset(chain.columns) or chain.empty:
        return {'inputs':{},'metrics':{},'errors':['옵션 체인 필수 컬럼/행 없음'],'model_usable':False,'context_usable':False,'iv_observed_oi_coverage':None,'policy_version':POLICY_VERSION}
    if not math.isfinite(spot) or spot <= 0:
        fatal.append('유효한 기준일 기초자산 가격 없음')
    for col in ('oi','volume','strike'):
        v=pd.to_numeric(chain[col],errors='coerce')
        chain[col]=v
        if col in ('oi','volume') and (v.dropna() % 1 != 0).any(): fatal.append(col+' 계약수는 정수여야 함')
        if not np.isfinite(v).all() or (v < 0).any() or (col=='strike' and (v<=0).any()):
            fatal.append(col+' 비정상 값')
    if not chain['type'].isin(['C','P']).all(): fatal.append('옵션 타입 비정상')
    if chain.duplicated(['expiry','strike','type']).any(): fatal.append('중복 옵션 계약')
    if chain.expiry.nunique()!=1: fatal.append('복수 만기 혼합')
    if 'multiplier' in chain:
        mult=pd.to_numeric(chain.multiplier,errors='coerce')
        if not np.isfinite(mult).all() or (mult<=0).any() or mult.nunique()!=1:
            fatal.append('승수 누락/불일치')
    try:
        if any(pd.isna(d) or pd.Timestamp(d).date() <= as_of for d in chain.expiry): fatal.append('만료/결측 만기 포함')
    except (TypeError, ValueError):
        fatal.append('만기 형식 오류')
    iv=pd.to_numeric(chain.iv,errors='coerce')
    observed=np.isfinite(iv)&(iv>0)
    denom=float(chain.oi.sum())
    coverage=float(chain.loc[observed,'oi'].sum()/denom) if denom>0 and not fatal else None
    expiry_ok='expiry_kind' in chain and chain.expiry_kind.eq('observed').all()
    inputs={
        'spot':Evidence('KRX/네이버 기초자산 종가',as_of.isoformat(),'invalid' if fatal else 'observed',fatal).to_dict(),
        'chain':Evidence(source,as_of.isoformat(),'invalid' if fatal else 'observed',fatal).to_dict(),
        'iv':Evidence(source,as_of.isoformat(),'observed' if observed.all() else 'estimated' if observed.any() else 'missing',[] if observed.all() else ['IV 결측/보간 의존']).to_dict(),
        'expiry':Evidence(str(chain.get('expiry_source',pd.Series(['요일 계산(명목 만기)'])).iloc[0]),as_of.isoformat(),'observed' if expiry_ok else 'estimated',[] if expiry_ok else ['공식 최종거래일 미확인']).to_dict(),
        'r':Evidence(r_source,as_of.isoformat(),'estimated',['기간 대응 무위험 할인곡선으로 검증되지 않음']).to_dict(),
        'q':Evidence(q_source,as_of.isoformat(),'estimated',['배당·선도가 모형 추정치; 실제 배당의 검증과 별개']).to_dict(),
        'dealer_position':Evidence('콜 롱·풋 숏 가정',as_of.isoformat(),'estimated',['실제 딜러 순재고 미확인']).to_dict(),
    }
    if expiry_ok and 'expiry_available_at' in chain:
        value=chain.expiry_available_at.iloc[0]
        inputs['expiry']['available_at']=None if pd.isna(value) else str(value)
    metrics={}
    for metric,deps in {'greeks':['spot','chain','iv','expiry','r','q'], 'walls':['spot','chain','iv','expiry','r','q'], 'signed_exposure':['spot','chain','iv','expiry','r','q','dealer_position'], 'zero_gamma':['spot','chain','iv','expiry','r','q','dealer_position'], 'pot':['spot','iv','expiry','r','q'], 'max_pain':['chain','expiry']}.items():
        reasons=[f'{d}: {reason}' for d in deps for reason in inputs[d]['reasons']]
        metrics[metric]={'usage':'research','dependencies':deps,'reasons':reasons or ['모형의 예측력 미검증']}
    return {'policy_version':POLICY_VERSION,'inputs':inputs,'metrics':metrics,'errors':fatal,
            'context_usable':not fatal,'model_usable':not fatal and bool(observed.any()),'iv_observed_oi_coverage':coverage}


def option_context(title, chain, spot, as_of, quality, spot_unit='포인트'):
    facts={'usage':'context','title':title,'as_of':as_of.isoformat(),'spot':spot if quality['context_usable'] else None,'spot_unit':spot_unit,'observations':{},'quality':quality}
    if quality['context_usable']:
        for typ,label in [('C','call'),('P','put')]:
            sub=chain[chain.type==typ]
            facts['observations'][label+'_oi']=int(sub.oi.sum())
            facts['observations'][label+'_volume']=int(sub.volume.sum())
    return facts


def quality_html(quality):
    rows=[]
    for name,e in quality['inputs'].items():
        fields=[name,e['kind'],e['source'],e.get('as_of') or '미확인',e.get('available_at') or '공개시각 미확인','; '.join(e['reasons']) or '관측 상태; 예측력 검증 아님']
        rows.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in fields)+'</tr>')
    deps=''.join('<li>'+html.escape(k+': '+', '.join(v['dependencies'])+' — '+'; '.join(v['reasons']))+'</li>' for k,v in quality['metrics'].items())
    c=quality.get('iv_observed_oi_coverage')
    coverage=f'{c:.1%}' if c is not None else '계산 불가'
    return '<details><summary>입력 출처·상태·계산 의존성</summary><table class="level-table"><tr><th>입력</th><th>상태</th><th>출처</th><th>기준일</th><th>공개시각</th><th>사유</th></tr>'+''.join(rows)+'</table><p>원본 IV의 OI 가중 커버리지: '+coverage+'</p><ul>'+deps+'</ul></details>'


def wrap_option_section(facts, research_html=None, error=None):
    q=facts['quality']; esc=html.escape
    labels={'call_oi':'콜 OI','put_oi':'풋 OI','call_volume':'콜 당일 거래량','put_volume':'풋 당일 거래량'}
    vals=' · '.join(esc(labels.get(k,k))+': '+format(v,',')+'계약' for k,v in facts['observations'].items()) or '계산 불가 — '+'; '.join(q['errors'])
    obs=facts['observations']
    call_oi=obs.get('call_oi'); put_oi=obs.get('put_oi')
    call_vol=obs.get('call_volume'); put_vol=obs.get('put_volume')
    oi_ratio=(put_oi/call_oi) if isinstance(call_oi,(int,float)) and call_oi>0 and isinstance(put_oi,(int,float)) else None
    vol_ratio=(put_vol/call_vol) if isinstance(call_vol,(int,float)) and call_vol>0 and isinstance(put_vol,(int,float)) else None
    ratio_text=[]
    if oi_ratio is not None: ratio_text.append(f'풋/콜 OI 비율은 {oi_ratio:.2f}')
    if vol_ratio is not None: ratio_text.append(f'풋/콜 당일 거래량 비율은 {vol_ratio:.2f}')
    ratio_sentence='이고, '.join(ratio_text)+'입니다. ' if ratio_text else ''
    explanation=(
        '<div class="beginner-note"><span class="beginner-note-label">관측값 읽기 (초보자용)</span>'
        +esc(ratio_sentence)
        +'OI(미결제약정)는 아직 청산되지 않은 계약의 누적 잔량이고, 거래량은 기준일에 거래된 계약 수입니다. '
        +'콜과 풋 중 어느 쪽 수량이 많다는 사실만으로 매수·매도 주체, 시장 방향 또는 실제 딜러 순포지션은 알 수 없습니다.</div>'
    )
    spot=facts.get('spot')
    spot_text=f'{spot:,.1f} {facts.get("spot_unit", "포인트")}' if isinstance(spot,(int,float)) and math.isfinite(spot) else '확인 불가'
    safe=f'<section><h2>{esc(facts["title"])} — 관측 요약</h2><p>기준일 {facts["as_of"]} 종가: {esc(spot_text)} · 실시간 시세 아님</p><p>{esc(vals)}</p>{explanation}{quality_html(q)}</section>'
    if research_html:
        safe+='<details class="research-panel"><summary>연구용 모형 — 기본 종합 판단·AI 입력에서 제외</summary><p>미검증 가정과 대체값에 의존합니다. 지지·저항·미래 확률의 검증 결과가 아닙니다.</p>'+research_html+'</details>'
    else:
        safe+='<p class="warn-banner">연구용 계산 불가 — '+esc(error or '유효한 IV 또는 필수 입력 없음')+'</p>'
    return safe


def attach_indicator_quality(result, series, as_of, source, dependencies, research_reason=None):
    evidence=assess_series(series,as_of,source,estimated=bool(research_reason) or result.is_proxy,
                           dependencies=dependencies,reason=research_reason)
    if evidence.kind in ('missing','stale','invalid'):
        result.score=None
        result.raw=None
    elif series is not None:
        at=series.loc[pd.to_datetime(series['date']).dt.date == as_of]
        if at.empty or not np.isfinite(at.iloc[-1]['score']):
            result.score=None
            evidence.kind='missing'
            evidence.reasons.append('기준일 점수 계산 불가/워밍업 부족')
    result.evidence=evidence.to_dict()
    result.evidence['backtest_eligible']=False
    result.evidence['backtest_reason']='원자료 공개시각/과거 수정 이력 미확인'
    result.evidence['usage']='context' if evidence.kind=='observed' and result.score is not None and not result.low_confidence else 'research' if result.score is not None else 'unavailable'
    return result


def indicator_quality_html(results, included):
    rows=[]
    warnings=[]
    for r in results:
        e=r.evidence or {}
        if e.get('kind') in ('stale','missing','invalid'):
            warnings.append(r.name+': '+e['kind']+' — '+'; '.join(e.get('reasons',[])))
        reasons=list(e.get('reasons',[]))
        if r.low_confidence: reasons.append('점수화 워밍업 부족')
        if r.name not in included and not reasons: reasons.append('매크로 배경/합성 대상 아님')
        cols=[r.name,'합성 포함' if r.name in included else '합성 제외',e.get('kind','미확인'),e.get('source','미확인'),e.get('as_of') or '미확인',', '.join(e.get('dependencies',[])), '; '.join(reasons) or '현재 상태 설명용; 전략 검증 전']
        rows.append('<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in cols)+'</tr>')
    warning_html='<p class="warn-banner">'+html.escape(' / '.join(warnings))+'</p>' if warnings else ''
    return '<section><h2>판단용 맥락 — 데이터 상태</h2><p>사용 구성: '+html.escape(', '.join(included) or '없음 — 계산 불가')+'</p>'+warning_html+'<details class="quality-details"><summary>지표별 출처·기준일·제외 사유</summary><p>관측 상태는 매매 신호의 검증을 뜻하지 않습니다. 공개시각이 확인되지 않은 과거 자료는 체결 가능한 백테스트 입력으로 승인되지 않습니다.</p><table class="level-table"><tr><th>지표</th><th>합성</th><th>상태</th><th>출처</th><th>기준일</th><th>의존 입력</th><th>사유</th></tr>'+''.join(rows)+'</table></details></section>'
