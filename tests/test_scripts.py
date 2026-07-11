import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import alert  # noqa: E402
import analyze  # noqa: E402
import scan  # noqa: E402


def closed_candles(count=200):
    closes = [100.0 + i * 0.1 for i in range(count)]
    return {
        "timestamps": list(range(count)),
        "confirmed": [True] * count,
        "opens": closes,
        "highs": [x + 0.2 for x in closes],
        "lows": [x - 0.2 for x in closes],
        "closes": closes,
        "volumes": [1.0] * count,
        "meta": {"raw_count": count + 1, "confirmed_count": count, "dropped_unconfirmed": 1, "last_confirmed_ts": count - 1, "last_response_ts": count},
    }


class ScriptSemanticsTests(unittest.TestCase):
    def test_scan_does_not_rank_empty_ratio_objects_as_ready(self):
        missing = scan.missing_primary_derivatives({
            "funding_rate_8h": 0.0,
            "oi_usd": 1.0,
            "global_ls": {},
            "top_position": {"ratio": None},
            "taker_buysell": {"last": None},
        })
        self.assertIn("Binance全站账户比", missing)
        self.assertIn("Binance头部持仓比", missing)
        self.assertIn("Taker", missing)

    def test_alert_default_is_only_a_live_warning(self):
        original_argv, original_price = sys.argv, alert.pc.okx_price
        alert.pc.okx_price = lambda _sym, _errors: {"last": 99.0, "chg24h_pct": -1.0}
        sys.argv = ["alert.py", "ETH", "100", "110"]
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                code = alert.main()
        finally:
            sys.argv, alert.pc.okx_price = original_argv, original_price
        rendered = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("下破预警", rendered)
        self.assertIn("未做已收盘确认", rendered)
        self.assertNotIn("已收盘确认破位", rendered)

    def test_alert_requires_opt_in_for_closed_confirmation(self):
        original_argv = sys.argv
        original_price, original_candles = alert.pc.okx_price, alert.pc.okx_candles
        alert.pc.okx_price = lambda _sym, _errors: {"last": 99.0, "chg24h_pct": -1.0}
        alert.pc.okx_candles = lambda *_args: {**closed_candles(5), "closes": [102.0, 99.0, 98.0, 97.0, 96.0]}
        sys.argv = ["alert.py", "ETH", "100", "110", "--confirm-closed", "5m", "--profile", "conservative"]
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                code = alert.main()
        finally:
            sys.argv, alert.pc.okx_price, alert.pc.okx_candles = original_argv, original_price, original_candles
        self.assertEqual(code, 0)
        self.assertIn("已收盘确认破位", output.getvalue())

    def test_profile_report_has_candidates_not_high_win_or_main_strategy(self):
        originals = {
            "price": analyze.pc.okx_price,
            "candles": analyze.pc.okx_candles,
            "okx_funding": analyze.pc.okx_funding,
            "derivs": analyze.pc.bn_derivs,
            "depth": analyze.pc.okx_depth_imbalance,
            "bybit": analyze.pc.bybit_funding,
            "argv": sys.argv,
        }
        analyze.pc.okx_price = lambda _sym, _errors: {"last": 119.9, "open24h": 100.0, "high24h": 121.0, "low24h": 99.0, "chg24h_pct": 1.0, "bid": 119.8, "ask": 120.0}
        analyze.pc.okx_candles = lambda *_args: closed_candles()
        analyze.pc.okx_funding = lambda _sym, _errors: 0.0
        analyze.pc.bn_derivs = lambda _sym, _bar, _errors: {
            "funding_rate_8h": 0.0, "oi_usd": 10.0, "oi_trend": 1, "oi_chg_window_pct": 1.0,
            "basis_pct": 0.0, "global_ls": {"ratio": 1.0, "trend": 0},
            "top_position": {"ratio": 1.0, "trend": 0}, "top_account": {"ratio": 1.0, "trend": 0},
            "taker_buysell": {"last": 1.0, "series": [1.0], "trend": 0},
        }
        analyze.pc.okx_depth_imbalance = lambda _sym, _errors: {"ratio": 1.0}
        analyze.pc.bybit_funding = lambda _sym, _errors: 0.0
        sys.argv = ["analyze.py", "ETH", "5m", "--profile", "active"]
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                analyze.main()
        finally:
            sys.argv = originals["argv"]
            analyze.pc.okx_price = originals["price"]
            analyze.pc.okx_candles = originals["candles"]
            analyze.pc.okx_funding = originals["okx_funding"]
            analyze.pc.bn_derivs = originals["derivs"]
            analyze.pc.okx_depth_imbalance = originals["depth"]
            analyze.pc.bybit_funding = originals["bybit"]
        rendered = output.getvalue()
        self.assertIn("档位：**active**", rendered)
        self.assertIn("候选情景（不预设唯一选择", rendered)
        self.assertNotIn("高胜率", rendered)
        self.assertNotIn("主策略", rendered)


if __name__ == "__main__":
    unittest.main()
