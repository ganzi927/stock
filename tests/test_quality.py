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
import stock_options_main
import outlook
import reference_data as ref
from combined_main import _report_is_current
from dealer_positioning import fill_iv_smile
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
        self.assertTrue(_report_is_current({'options_complete':True,'quality_policy_version':q.POLICY_VERSION}))

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
            st.enter_context(patch.object(main,'generate_commentary',return_value=None))
            st.enter_context(patch.object(main,'build_fgi_section',side_effect=render))
            html,_,_,total,facts,_=main.generate_fgi_section(ASOF)
        self.assertEqual(set(facts['included']),{'Momentum','Volatility','Put/Call Ratio'})
        self.assertEqual(total,float(captured['total_trend_scores'].iloc[-1]))
        self.assertEqual(facts['quality']['Strength']['usage'],'research')
        self.assertNotIn('Strength',facts['indicators'])
        self.assertIn('사용 구성',html)

if __name__=='__main__':unittest.main()
