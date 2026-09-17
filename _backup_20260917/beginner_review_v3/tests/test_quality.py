"""Quality policy tests: external responses and references are synthetic fixtures."""
from contextlib import ExitStack
from datetime import date
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import data_quality as q
import indicators as ind
import main
import options_main
import options_report
import stock_options_main
import outlook
import report
import reference_data as ref
from combined_main import _report_is_current, REPORT_CONTRACT_VERSION
from dealer_positioning import fill_iv_smile, build_scenarios
from validate_inputs import inspect_cache

ASOF=date(2026,9,15)

def chain(iv=None):
    return pd.DataFrame(dict(strike=[90.,100.,110.,90.,100.,110.],type=['C']*3+['P']*3,
        oi=[10]*6,volume=[2]*6,iv=iv or [20.]*6,expiry=[date(2026,10,8)]*6,
        close=[11.,5.,2.,1.,5.,12.],multiplier=[10.]*6))

def series(n=500):
    return pd.DataFrame(dict(date=pd.bdate_range(end=ASOF,periods=n),raw=[1.]*n,score=[60.]*n))

class QualityTests(unittest.TestCase):
    def test_putcall_regular_session_only(self):
        import krx_api
        rows=[]
        for session,call,put in [('정규',10,20),('야간',100,1)]:
            for typ,vol in [('CALL',call),('PUT',put)]:
                rows.append(dict(PROD_NM='코스피200 옵션',ISU_NM='test ('+session+')',RGHT_TP_NM=typ,ACC_TRDVOL=str(vol)))
        with patch.object(krx_api,'_get',return_value={'OutBlock_1':rows}):
            self.assertEqual(krx_api.fetch_kospi200_option_putcall_one_day('20260915'),2.)

    def test_render_places_estimates_inside_research_panel(self):
        import report
        from bs4 import BeautifulSoup
        d=series()
        observed=ind.latest_result(d,'Momentum',False,'observed fixture')
        estimated=ind.latest_result(d,'Strength',True,'research fixture')
        q.attach_indicator_quality(observed,d,ASOF,'test',['price'])
        q.attach_indicator_quality(estimated,d,ASOF,'test',['price'])
        with patch.object(report,'total_trend_chart',return_value=''), patch.object(report,'gauge_chart',return_value=''):
            page=report.build_fgi_section(60.,[observed,estimated],d.date,d.score,{},sentiment_score=60.,trend_score=60.)
        soup=BeautifulSoup(page,'html.parser')
        panel=soup.select_one('details.research-panel')
        self.assertIn('Strength',panel.get_text())
        self.assertNotIn('Momentum',panel.get_text())

    def test_stale_cannot_be_current(self):
        d=series().iloc[:-1]
        r=ind.latest_result(d,'Momentum',False,'')
        q.attach_indicator_quality(r,d,ASOF,'test',['price'])
        self.assertIsNone(r.score);self.assertEqual(r.evidence['kind'],'stale')
        self.assertIsNone(ind.total_fgi([r]))

    def test_missing_current_score_cannot_reuse_old(self):
        d=series();d.loc[d.index[-1],'score']=np.nan
        r=ind.latest_result(d,'Momentum',False,'')
        q.attach_indicator_quality(r,d,ASOF,'test',['price'])
        self.assertIsNone(r.score)

    def test_estimate_excluded_but_preserved(self):
        d=series();r=ind.latest_result(d,'Momentum',True,'')
        q.attach_indicator_quality(r,d,ASOF,'test',['price'])
        self.assertEqual(r.score,60);self.assertEqual(r.evidence['usage'],'research')
        self.assertIsNone(ind.total_fgi([r]))
        self.assertIn('합성 제외',q.indicator_quality_html([r],[]))

    def test_dependency_and_iv_coverage(self):
        c=chain([20.,np.nan,20.,20.,20.,20.])
        result=q.option_quality(c,100.,ASOF,'constant','constant')
        self.assertAlmostEqual(result['iv_observed_oi_coverage'],5/6)
        self.assertIn('dealer_position',result['metrics']['zero_gamma']['dependencies'])
        self.assertEqual(result['metrics']['zero_gamma']['usage'],'research')
        self.assertIn('expiry',result['metrics']['pot']['dependencies'])

    def test_bad_chain_and_missing_iv(self):
        for c in [chain().assign(oi=-1),pd.concat([chain(),chain()]),chain().assign(multiplier=[10,20,10,10,10,10])]:
            self.assertFalse(q.option_quality(c,100.,ASOF,'r','q')['context_usable'])
        r=q.option_quality(chain([np.nan]*6),100.,ASOF,'r','q')
        self.assertTrue(r['context_usable']);self.assertFalse(r['model_usable'])

    def test_iv_provenance_and_input_unchanged(self):
        c=chain([20.,np.nan,30.,20.,np.nan,30.]);original=c.copy(deep=True)
        g=fill_iv_smile(c,100.)
        self.assertEqual(g.iv_method.tolist(),['observed','interpolated','observed']*2)
        self.assertTrue(np.isnan(g.iv_original.iloc[1]))
        pd.testing.assert_frame_equal(c,original)

    def test_future_expiry_record_excluded_and_holiday_correction(self):
        nominal=date(2026,10,8)
        row=dict(product='test',nominal_expiry=nominal.isoformat(),expiry='2026-10-07',
                 source='https://global.krx.co.kr/test',verification_note='synthetic fixture',available_at='2026-09-16T09:00:00+09:00')
        data=dict(schema_version=1,expiries=[row],dividends=[],dividend_coverage=[])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ref.json';p.write_text(json.dumps(data))
            actual,e=ref.resolve_expiry('test',nominal,ASOF,p)
            self.assertEqual(actual,nominal);self.assertEqual(e['kind'],'estimated')
            row['available_at']='2026-09-14T09:00:00+09:00';p.write_text(json.dumps(data))
            actual,e=ref.resolve_expiry('test',nominal,ASOF,p)
            self.assertEqual(actual,date(2026,10,7));self.assertEqual(e['kind'],'observed')
            row['source']='https://global.krx.co.kr.evil.example/test';p.write_text(json.dumps(data))
            self.assertEqual(ref.resolve_expiry('test',nominal,ASOF,p)[1]['kind'],'estimated')

    def test_dividend_requires_complete_and_known(self):
        row=dict(name='test',event_id='q3',ex_date='2026-09-29',pay_date='2026-11-15',amount=100,
            source='https://www.samsung.com/test',verification_note='synthetic fixture',available_at='2026-09-01T09:00:00+09:00')
        data=dict(schema_version=1,expiries=[],dividends=[row],dividend_coverage=[])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ref.json';p.write_text(json.dumps(data))
            got,complete,reasons=ref.dividend_schedule('test',ASOF,date(2026,10,8),p)
            self.assertFalse(complete);self.assertEqual(got[0]['pay_date'],date(2026,11,15))
            cover=dict(row,start='2026-09-01',end='2026-10-08',complete=True)
            data['dividend_coverage']=[cover];p.write_text(json.dumps(data))
            self.assertTrue(ref.dividend_schedule('test',ASOF,date(2026,10,8),p)[1])
            row['available_at']='2026-09-16T09:00:00+09:00';data['dividend_coverage']=[];p.write_text(json.dumps(data))
            self.assertEqual(ref.dividend_schedule('test',ASOF,date(2026,10,8),p)[0],[])

    @patch.dict(os.environ,{'KFGI_RESEARCH_AI':'0'})
    def test_options_default_no_ai_research_leak(self):
        c=chain()
        with patch.object(options_main,'fetch_option_chain',return_value=c),patch.object(options_main,'_resolve_rq',return_value=(.03,.01,False,'가정')),patch.object(options_main,'_update_iv_rank_cache',return_value=None),patch.object(options_main,'build_section_html',return_value='RESEARCH_SENTINEL'),patch.object(options_main,'generate_commentary') as ai:
            html,facts=options_main.build_product_section('test','test','20260915',ASOF,100.,'test.csv',None,pd.DataFrame())
        ai.assert_not_called();self.assertIn('<details class="research-panel">',html)
        self.assertEqual(facts['usage'],'context');self.assertNotIn('levels',facts)
        prompt=outlook.build_outlook_prompt(ASOF,dict(total=60,trend=60,sentiment=60,indicators={},quality={}),[dict(facts,levels=['SECRET_RESEARCH'],flow='SECRET_FLOW')])
        self.assertNotIn('SECRET_RESEARCH',prompt);self.assertNotIn('SECRET_FLOW',prompt)

    def test_beginner_explanations_survive_without_ai(self):
        c=chain()
        quality=q.option_quality(c,100.,ASOF,'r','q')
        facts=q.option_context('테스트 옵션',c,100.,ASOF,quality)
        observed=q.wrap_option_section(facts,'RESEARCH')
        self.assertIn('관측값 읽기 (초보자용)',observed)
        self.assertIn('풋/콜 OI 비율은 1.00',observed)
        self.assertIn('누적 잔량',observed)

        levels=options_report.Levels(
            spot=100.,max_pain=100.,dex_neutral_maxpain=None,zero_gamma=95.,
            call_wall=110.,put_wall=90.,strike_min=80.,strike_max=120.
        )
        model=options_report._beginner_model_explanation(
            100.,levels,{'call_wall':.25,'put_wall':.35,'zero_gamma':.50,'max_pain':1.0},
            (20.,25.,-5.),{'oi_skew':.2}
        )
        self.assertIn('모형 읽기 (초보자용)',model)
        self.assertIn('Call Wall',model)
        self.assertIn('110.0',model)
        self.assertIn('지지·저항이나 다음 가격을 뜻하지 않으며',model)

        d=series()
        context=ind.latest_result(d,'Momentum',False,'fixture')
        research=ind.latest_result(d,'Strength',True,'fixture')
        q.attach_indicator_quality(context,d,ASOF,'test',['price'])
        q.attach_indicator_quality(research,d,ASOF,'test',['price'],'research')
        fgi=report._beginner_fgi_explanation([context,research],['Momentum'],60.,55.,65.)
        self.assertIn('오늘의 지표 읽기 (초보자용)',fgi)
        self.assertIn('252거래일',fgi)
        self.assertIn('지수/125일 이동평균 비율은 1.000배',fgi)
        self.assertIn('Strength',fgi)

    def test_stock_risk_planner_is_user_budget_math_not_recommendation(self):
        self.assertEqual(options_report.calculate_loss_limit(250000,10,100000),240000)
        self.assertIsNone(options_report.calculate_loss_limit(250000,1.5,100000))
        self.assertIsNone(options_report.calculate_loss_limit(250000,1,250000))
        levels=options_report.Levels(
            spot=250000.,max_pain=255000.,dex_neutral_maxpain=None,zero_gamma=240000.,
            call_wall=300000.,put_wall=220000.,strike_min=200000.,strike_max=320000.
        )
        scenarios=build_scenarios(levels)
        panel=options_report._stock_risk_planner_html('005930',250000.,levels,scenarios)
        self.assertIn('상단 관찰가격',panel)
        self.assertIn('255,000원',panel)
        self.assertIn('하단 관찰가격',panel)
        self.assertIn('240,000원',panel)
        self.assertNotIn('무효화',panel)
        self.assertNotIn('distanceRatio',panel)
        self.assertIn('입력값은 저장하거나 전송하지 않습니다',panel)
        self.assertIn('entry - loss / qty',panel)

        with patch.object(options_report,'gex_profile_chart',return_value=''),patch.object(options_report,'vol_smile_chart',return_value=''):
            index_html=options_report.build_section_html(
                title='코스피200 옵션',expiry_label='fixture',spot=250000.,levels=levels,
                profile=pd.DataFrame(),chain_with_greeks=pd.DataFrame(),scenarios=scenarios,
                net_dex=0.,net_vex=0.,net_charm=0.,iv_rank=None
            )
        self.assertNotIn('내 손실한도 계산기',index_html)

    def test_outlook_explains_each_observation_without_research(self):
        facts=dict(
            usage='context',title='코스피200 옵션 (정규월물)',as_of=ASOF.isoformat(),spot=100.,
            observations=dict(call_oi=100,put_oi=50,call_volume=20,put_volume=30),quality={}
        )
        prompt=outlook.build_outlook_prompt(
            ASOF,dict(total=60,trend=55,sentiment=65,indicators={},quality={}),[facts]
        )
        self.assertIn('풋/콜 OI 비율: 0.50',prompt)
        self.assertIn('정규월물·위클리·삼성전자·SK하이닉스',prompt)
        self.assertNotIn('Zero Gamma',outlook._fmt_opt(facts))

    def test_missing_iv_keeps_observations(self):
        with patch.object(options_main,'fetch_option_chain',return_value=chain([np.nan]*6)),patch.object(options_main,'_resolve_rq') as rq:
            html,facts=options_main.build_product_section('test','test','20260915',ASOF,100.,'test.csv',None,pd.DataFrame())
        rq.assert_not_called();self.assertIn('계산 불가',html)
        self.assertEqual(facts['observations']['call_oi'],30)

    def test_stock_does_not_use_hardcoded_dividends(self):
        with patch.object(stock_options_main,'_resolve_stock_spot',return_value=100.),patch.object(stock_options_main,'fetch_stock_option_chain',return_value=chain([np.nan]*6)),patch.object(stock_options_main,'dividend_schedule',return_value=([],False,['미확인'])):
            html,facts=stock_options_main.build_stock_option_section('삼성전자','005930','20260915',ASOF,None,'test.csv')
        self.assertIn('상수',facts['quality']['inputs']['q']['source'].replace('종목별 평상시 가정','상수'))
        self.assertEqual(facts['quality']['dividend_records'],[])

    def test_legacy_meta_rebuild(self):
        self.assertFalse(_report_is_current({'options_complete':True}))
        base={'options_complete':True,'quality_policy_version':q.POLICY_VERSION}
        self.assertFalse(_report_is_current(base))
        self.assertFalse(_report_is_current(dict(base,report_contract_version=REPORT_CONTRACT_VERSION-1)))
        self.assertTrue(_report_is_current(dict(base,report_contract_version=REPORT_CONTRACT_VERSION)))

    def test_deterministic_outlook_no_llm_and_no_research(self):
        fgi=dict(total=60.,trend=40.,sentiment=70.,included=['Momentum'],
                 indicators={'Momentum':40.,'Strength':99999.},
                 quality={'Momentum':{'usage':'context'},'Strength':{'usage':'research'}})
        facts=dict(usage='context',title='삼성전자 옵션',as_of=ASOF.isoformat(),spot=250000.,spot_unit='원',
                   observations=dict(call_oi=100,put_oi=50,call_volume=20,put_volume=30),levels=['SECRET'])
        with patch.object(outlook,'generate_commentary') as ai:
            page=outlook.build_outlook_section(ASOF,fgi,[facts,dict(facts,title='STALE',as_of='2026-09-14')])
        ai.assert_not_called()
        self.assertIn('250,000.0 원',page)
        self.assertIn('풋/콜 OI 비율: 0.50',page)
        for forbidden in ('SECRET','99999','STALE','상승 추진력','방어수요'):
            self.assertNotIn(forbidden,page)

    def test_observation_contract_preserves_maxpain_without_price_path(self):
        from bs4 import BeautifulSoup
        levels=options_report.Levels(spot=1750000.,max_pain=1300000.,dex_neutral_maxpain=None,
            zero_gamma=None,call_wall=1800000.,put_wall=1700000.,strike_min=1000000.,strike_max=2000000.)
        rows=build_scenarios(levels)
        pain=next(r for r in rows if r['name']=='MaxPain (부분 체인·비표준)')
        self.assertEqual(pain['value'],1300000.)
        self.assertEqual(pain['position'],'아래')
        self.assertAlmostEqual(pain['distance_pct'],(1300000/1750000-1)*100)
        for row in rows:
            self.assertEqual(set(row),{'name','value','distance_pct','position','definition','limitation'})
        with patch.object(options_report,'gex_profile_chart',return_value=''),patch.object(options_report,'vol_smile_chart',return_value=''):
            page=options_report.build_section_html('test','fixture',levels.spot,levels,pd.DataFrame(),pd.DataFrame(),rows,0,0,0,None)
        text=BeautifulSoup(page,'html.parser').get_text(' ',strip=True)
        for forbidden in ('Trigger:','Target:','무효화','부근 유지','이탈 시'):
            self.assertNotIn(forbidden,text)
        self.assertIn('1,300,000.0',text)

    def test_score_explanation_inversion_and_strength_definition(self):
        results=[]
        for name,score in [('Momentum',20.),('Volatility',20.),('Put/Call Ratio',80.),('Strength',60.)]:
            r=ind.latest_result(series().assign(score=score),name,False,'fixture')
            q.attach_indicator_quality(r,series().assign(score=score),ASOF,'test',['price'],
                                       'research' if name=='Strength' else None)
            results.append(r)
        text=report._beginner_fgi_explanation(results,['Momentum','Volatility','Put/Call Ratio'],40.,20.,50.)
        for expected in ('100−백분위','역산 20점','높은 쪽','당일 표시값(raw)','5일 평균','60.0점','52주 신고가−신저가','252일 고저 범위'):
            self.assertIn(expected,text)
        self.assertNotIn('상승·하락 종목의 규모',text)

    def test_observed_close_and_quality_disclosure(self):
        from bs4 import BeautifulSoup
        c=chain();quality=q.option_quality(c,100.,ASOF,'r','q')
        for unit in ('원','포인트'):
            facts=q.option_context('test',c,100.,ASOF,quality,spot_unit=unit)
            page=BeautifulSoup(q.wrap_option_section(facts,'RESEARCH'),'html.parser')
            text=page.section.get_text(' ',strip=True)
            self.assertIn('100.0 '+unit,text)
            self.assertLess(text.index('종가'),text.index('콜 OI'))
        r=ind.latest_result(series(),'Momentum',False,'')
        q.attach_indicator_quality(r,series().iloc[:-1],ASOF,'test',['price'])
        page=BeautifulSoup(q.indicator_quality_html([r],[]),'html.parser')
        self.assertFalse(page.select_one('details').has_attr('open'))
        self.assertIsNone(page.select_one('.warn-banner').find_parent('details'))
        self.assertIn('stale',page.select_one('.warn-banner').get_text())

    def test_calculator_javascript_invalidates_old_result(self):
        import subprocess
        from bs4 import BeautifulSoup
        levels=options_report.Levels(spot=250000.,max_pain=255000.,dex_neutral_maxpain=None,
            zero_gamma=240000.,call_wall=300000.,put_wall=220000.,strike_min=200000.,strike_max=320000.)
        soup=BeautifulSoup(options_report._stock_risk_planner_html('test',250000.,levels,build_scenarios(levels)),'html.parser')
        self.assertIsNone(soup.select_one('.observation-levels').find_parent(class_='risk-planner'))
        script=soup.script.string
        harness=r'''
const vm=require('vm'),assert=require('assert');
const listeners={}; let click;
const fields=Object.fromEntries(['entry','quantity','loss'].map(k=>[k,{value:'',addEventListener:(ev,fn)=>listeners[k+ev]=fn}]));
const out={textContent:''};
const root={querySelector:s=>s==='.risk-result'?out:s==='.risk-button'?{addEventListener:(ev,fn)=>click=fn}:fields[s.match(/data-field="([a-z]+)"/)[1]],querySelectorAll:()=>Object.values(fields)};
vm.runInNewContext(SCRIPT,{document:{getElementById:()=>root}});
function calc(){fields.entry.value='250000';fields.quantity.value='10';fields.loss.value='100000';click();assert(out.textContent.includes('240,000원'));assert(out.textContent.includes('수량 10주'));assert(out.textContent.includes('매수가 250,000원'));}
for(const field of ['entry','quantity','loss'])for(const event of ['input','change']){calc();fields[field].value='200000';listeners[field+event]();assert(!out.textContent.includes('240,000'));assert(out.textContent.includes('다시'));}
for(const [entry,qty,loss] of [['250000','0','100000'],['250000','1.5','100000'],['250000','10','2500000'],['250000','10','']]){fields.entry.value=entry;fields.quantity.value=qty;fields.loss.value=loss;click();assert(!out.textContent.includes('내 손실한도 가격'));}
'''.replace('SCRIPT',json.dumps(script))
        checked=subprocess.run(['node','-e',harness],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(checked.returncode,0,checked.stderr)

    def test_offline_audit_flags_future_stale_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=pd.DataFrame(dict(date=['2026-09-14','2026-09-16'],close=[100,200]))
            d.to_csv(Path(tmp)/'kospi200.csv',index=False)
            r=inspect_cache(tmp,ASOF)['kospi200.csv']
            self.assertEqual(r['status'],'stale');self.assertEqual(r['future_rows_excluded'],1)
            self.assertEqual(len(r['sha256']),64);self.assertFalse(r['backtest_eligible'])

    def test_main_composition_and_history_match(self):
        d=series();prices=pd.DataFrame(dict(date=d.date,close=100.,volume=100.))
        captured={}
        def render(**kwargs): captured.update(kwargs);return '<p>FGI</p>'
        with ExitStack() as st:
            st.enter_context(patch.object(main,'update_cache',return_value=prices))
            st.enter_context(patch.object(main,'update_krx_cache',return_value=pd.DataFrame()))
            st.enter_context(patch.object(main,'update_market_cache',return_value=pd.DataFrame()))
            st.enter_context(patch.object(main,'compute_breadth_and_strength_raw',return_value=pd.DataFrame()))
            st.enter_context(patch.object(main,'synthetic_bond10y_index',return_value=prices))
            st.enter_context(patch.object(main,'fetch_credit_spread',return_value=pd.DataFrame()))
            for fn in ('compute_momentum','compute_safe_haven','compute_credit_spread','compute_volatility_real','compute_strength_real','compute_breadth_real','compute_putcall_real'):
                st.enter_context(patch.object(ind,fn,return_value=d.copy()))
            st.enter_context(patch.object(main,'build_fgi_section',side_effect=render))
            html,_,_,total,facts,_=main.generate_fgi_section(ASOF)
        self.assertEqual(set(facts['included']),{'Momentum','Volatility','Put/Call Ratio'})
        self.assertEqual(total,float(captured['total_trend_scores'].iloc[-1]))
        self.assertEqual(facts['quality']['Strength']['usage'],'research')
        self.assertNotIn('Strength',facts['indicators'])
        self.assertIn('사용 구성',html)

if __name__=='__main__':unittest.main()
