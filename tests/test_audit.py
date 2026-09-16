"""Regression cases from the evidence audit; synthetic fixtures, no external API calls."""
import contextlib
from datetime import date
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backtest
import dealer_positioning as dp
import indicators as ind
import options_data
import stock_options_data
import outlook
from greeks import compute_greeks
from krx_market import compute_breadth_and_strength_raw
from options_main import _update_iv_rank_cache


class AuditTests(unittest.TestCase):
    def test_iv_percent_units(self):
        c = pd.DataFrame({'strike': [80., 100., 125.], 'iv': [20., np.nan, 30.], 'type': ['C']*3})
        self.assertAlmostEqual(dp.fill_iv_smile(c, 100).iv.iloc[1], 25.)

    def test_invalid_greek_inputs(self):
        for field in ('spot', 'strike', 't_years', 'sigma'):
            for invalid in (0., -1., np.nan, np.inf):
                args = dict(spot=[100.], strike=[100.], t_years=[.2], sigma=[.2], is_call=[True])
                args[field] = [invalid]
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    compute_greeks(**args)

    def test_tiny_positive_inputs_consistent(self):
        g = compute_greeks([100.], [100.], [1e-8], [1e-5], [True], r=0., q=0.)
        expected = 1 / (np.sqrt(2*np.pi)*100*1e-5*np.sqrt(1e-8))
        self.assertAlmostEqual(g['gamma'][0]/expected, 1., places=8)

    @patch.dict('os.environ', {'KRX_API_KEY': 'synthetic-test-key'})
    def test_expired_only_chain_is_empty(self):
        common = dict(IMP_VOLT='20', ACC_OPNINT_QTY='1', ACC_TRDVOL='1', TDD_CLSPRC='1', NXTDD_BAS_PRC='1')
        cases = [
            (options_data, dict(common, PROD_NM=options_data.REGULAR_PROD, ISU_NM='코스피200 C 202609 100 (정규)'), options_data.REGULAR_PROD),
            (stock_options_data, dict(common, PROD_NM='삼성전자 옵션', ISU_NM='삼성전자 C 202609 100( 10)'), '삼성전자'),
        ]
        for module, row, name in cases:
            response = Mock(); response.json.return_value = {'OutBlock_1': [row]}
            fn = module.fetch_option_chain if module is options_data else module.fetch_stock_option_chain
            with patch.object(module.requests, 'get', return_value=response):
                self.assertTrue(fn('20260910', name).empty)
                self.assertFalse(fn('20260909', name).empty)

    def test_high_oi_low_volume_preserved(self):
        # The large valid call OI makes 80 the unique minimum, despite zero daily volume.
        c = pd.DataFrame({'strike': [80., 100., 120.], 'type': ['C', 'C', 'P'], 'oi': [10000, 1, 1], 'volume': [0, 1, 1]})
        self.assertEqual(dp.compute_max_pain(c, spot=100), 80.)
        self.assertEqual(dp.compute_max_pain(c), 80.)

    def test_full_chain_and_window_differ(self):
        c = pd.DataFrame({'strike': [50., 90., 100., 110.], 'type': ['C','C','P','P'], 'oi': [10000,1,10,1]})
        self.assertEqual(dp.compute_max_pain(c), 50.)
        self.assertEqual(dp.compute_max_pain(c, spot=100), 100.)

    def test_walls_invariant_to_global_sign_flip(self):
        c = pd.DataFrame({'strike': [90., 110., 90., 110.], 'type': ['C','C','P','P'], 'gex': [1.,10.,-12.,-2.]})
        self.assertEqual(dp.find_walls(c, 100), dp.find_walls(c.assign(gex=-c.gex), 100))

    def test_sticky_reference_is_observed_spot(self):
        c = pd.DataFrame({'strike': [80.,100.,125.], 'type':['C']*3, 'iv':[20.,25.,30.], 'oi':[1]*3, 'expiry':[date(2026,10,8)]*3})
        grid = np.array([70.,90.,100.,170.])
        sticky = dp.gex_profile(c,date(2026,9,15),grid,iv_sticky_moneyness=True,reference_spot=100.)
        fixed = dp.gex_profile(c,date(2026,9,15),grid)
        self.assertAlmostEqual(sticky.loc[100.], fixed.loc[100.])
        with self.assertRaises(ValueError):
            dp.gex_profile(c,date(2026,9,15),grid,iv_sticky_moneyness=True)

    def test_breadth_one_sided_and_flat(self):
        rows = []
        for day, change in zip(pd.date_range('2026-01-01',periods=3), [1.,-1.,0.]):
            for code in ['A','B']:
                rows.append(dict(date=day,ISU_CD=code,close=100.,fluc_rt=change,trdvol=5.,mktcap=100.))
        got = compute_breadth_and_strength_raw(pd.DataFrame(rows)).breadth_raw
        self.assertEqual(list(got[:2]), [1.,-1.]); self.assertTrue(np.isnan(got.iloc[2]))

    def test_percentile_missing_data(self):
        s = pd.Series([5.]*252); s.iloc[::3] = np.nan; s.iloc[-1] = 5.
        self.assertEqual(ind._rolling_percentile_score(s).iloc[-1],50.)
        s.iloc[-1] = np.nan
        self.assertTrue(np.isnan(ind._rolling_percentile_score(s).iloc[-1]))
        s = pd.Series(np.arange(252,dtype=float)); s.iloc[::3] = np.nan
        self.assertEqual(ind._rolling_percentile_score(s).iloc[-1],100.)

    def test_unsupported_score_ci_not_reported(self):
        s = pd.DataFrame({'date':pd.date_range('2020-01-01',periods=300),'raw':5.,'score':50.})
        self.assertIsNone(ind.latest_result(s,'test',False,'test').score_ci)

    def test_iv_percentile_asof(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'iv.csv'
            days = pd.bdate_range('2025-01-01',periods=180)
            pd.DataFrame({'date':days,'atm_iv':np.arange(180.)+10}).to_csv(path,index=False)
            asof = days[-1].date()
            before = _update_iv_rank_cache(path,asof,70.)
            df = pd.read_csv(path)
            df = pd.concat([df,pd.DataFrame({'date':['2027-01-01'],'atm_iv':[1000.]})],ignore_index=True)
            df.to_csv(path,index=False)
            self.assertEqual(before,_update_iv_rank_cache(path,asof,70.))
            self.assertEqual(len(pd.read_csv(path)),181)

    def test_bootstrap_constant_and_mask_axis(self):
        x = pd.Series(np.arange(160.)); y = x*2
        self.assertIsNone(backtest.boot_ic(x*0,y,20,b=10))
        x.iloc[::2] = np.nan
        original = backtest._sb_index
        with patch.object(backtest,'_sb_index', wraps=original) as sb:
            got = backtest.boot_ic(x,y,20,b=10)
            self.assertTrue(all(c.args[0]==160 for c in sb.call_args_list))
            self.assertEqual(got['n'],80)
            self.assertAlmostEqual(got['ic'],1.)

    def test_forward_horizons_and_report(self):
        n=200
        m=pd.DataFrame({'date':pd.bdate_range('2020-01-01',periods=n),'kospi200':100*np.exp(np.arange(n)/1000),'vk_level':np.nan})
        for i,c in enumerate(backtest.SEVEN): m[c]=(np.arange(n)+i)%100
        full=backtest.fwd_returns(backtest.add_composites(m))
        self.assertEqual(full.fwd20.notna().sum(),180)
        self.assertEqual(full.fwd120.notna().sum(),80)
        with patch.object(backtest,'build_series',return_value=m), patch.object(backtest,'boot_ic',return_value=None) as boot, contextlib.redirect_stdout(io.StringIO()) as out:
            backtest.run(None,False)
        self.assertTrue(all(len(c.args[0])==200 for c in boot.call_args_list))
        self.assertNotIn('겨우 0 을 벗어나는',out.getvalue())
        self.assertIn('다중검정',out.getvalue())

    def test_ai_sentiment_and_rejection(self):
        fgi=dict(total=50.,trend=50.,sentiment=20.,indicators={})
        self.assertIn('투심 낮음=평활 변동성·풋콜 거래량비 높음',outlook._fmt_fgi(fgi))
        with patch.object(outlook,'build_outlook_prompt',return_value='레벨 1000.0'), patch.object(outlook,'generate_commentary',return_value='레벨 9999.0'):
            self.assertIsNone(outlook.build_outlook_section(date(2026,9,15),fgi,[{}]))

if __name__=='__main__':
    unittest.main()
