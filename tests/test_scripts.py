import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import alert  # noqa: E402
import analyze  # noqa: E402
import scan  # noqa: E402


def closed_candles(count=200):
    interval = analyze.pc.BAR_INTERVAL_MS["5m"]
    current_open = analyze.pc.now_ms() // interval * interval
    closes = [100.0 + i * 0.1 for i in range(count)]
    timestamps = [current_open - (count - index) * interval for index in range(count)]
    return {
        "timestamps": timestamps,
        "confirmed": [True] * count,
        "opens": closes,
        "highs": [x + 0.2 for x in closes],
        "lows": [x - 0.2 for x in closes],
        "closes": closes,
        "volumes": [1.0] * count,
        "meta": {"bar": "5m", "interval_ms": interval, "raw_count": count + 1,
                 "confirmed_count": count, "dropped_unconfirmed": 1,
                 "last_confirmed_ts": timestamps[-1], "last_confirmed_close_ts": current_open,
                 "last_response_ts": current_open, "continuity_ok": True, "freshness_ok": True},
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
        alert.pc.okx_price = lambda _sym, _errors: {
            "last": 99.0, "chg24h_pct": -1.0, "timestamp": alert.pc.now_ms(), "freshness_ok": True,
        }
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
        alert.pc.okx_price = lambda _sym, _errors: {
            "last": 99.0, "chg24h_pct": -1.0, "timestamp": alert.pc.now_ms(), "freshness_ok": True,
        }
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
        analyze.pc.okx_price = lambda _sym, _errors: {
            "last": 119.9, "open24h": 100.0, "high24h": 121.0, "low24h": 99.0,
            "chg24h_pct": 1.0, "bid": 119.8, "ask": 120.0,
            "timestamp": analyze.pc.now_ms(), "freshness_ok": True,
        }
        analyze.pc.okx_candles = lambda *_args: closed_candles()
        analyze.pc.okx_funding = lambda _sym, _errors: {
            "rate": 0.0, "interval_hours": 8.0, "rate_8h_equiv": 0.0, "freshness_ok": True,
        }
        analyze.pc.bn_derivs = lambda _sym, _bar, _errors: {
            "funding_rate": 0.0, "funding_interval_hours": 8.0, "funding_rate_8h_equiv": 0.0,
            "funding_rate_8h": 0.0, "premium_freshness_ok": True,
            "oi_usd": 10.0, "oi_trend": 1, "oi_chg_window_pct": 1.0, "oi_freshness_ok": True,
            "basis_pct": 0.0, "global_ls": {"ratio": 1.0, "trend": 0, "freshness_ok": True},
            "top_position": {"ratio": 1.0, "trend": 0, "freshness_ok": True},
            "top_account": {"ratio": 1.0, "trend": 0, "freshness_ok": True},
            "taker_buysell": {"last": 1.0, "series": [1.0], "trend": 0, "freshness_ok": True},
        }
        analyze.pc.okx_depth_imbalance = lambda _sym, _errors: {"ratio": 1.0, "freshness_ok": True}
        analyze.pc.bybit_funding = lambda _sym, _errors: {
            "rate": 0.0, "interval_hours": 8.0, "rate_8h_equiv": 0.0, "freshness_ok": True,
        }
        sys.argv = ["analyze.py", "ETH", "5m", "--profile", "conservative"]
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
        self.assertIn("档位：**conservative**", rendered)
        self.assertIn("由 2 根 5m 已收盘K确认企稳", rendered)
        self.assertIn("候选情景（不预设唯一选择", rendered)
        self.assertNotIn("高胜率", rendered)
        self.assertNotIn("主策略", rendered)

    def test_no_trade_hard_gate_nulls_direction_candidates_and_sizing(self):
        originals = {
            "price": analyze.pc.okx_price, "candles": analyze.pc.okx_candles,
            "okx_funding": analyze.pc.okx_funding, "derivs": analyze.pc.bn_derivs,
            "depth": analyze.pc.okx_depth_imbalance, "bybit": analyze.pc.bybit_funding,
            "argv": sys.argv,
        }
        analyze.pc.okx_price = lambda *_: {
            "last": 119.9, "open24h": 100.0, "high24h": 121.0, "low24h": 99.0,
            "chg24h_pct": 1.0, "timestamp": analyze.pc.now_ms(), "freshness_ok": True,
        }
        analyze.pc.okx_candles = lambda *_: closed_candles()
        analyze.pc.okx_funding = lambda *_: None
        analyze.pc.bn_derivs = lambda *_: {}
        analyze.pc.okx_depth_imbalance = lambda *_: None
        analyze.pc.bybit_funding = lambda *_: None
        sys.argv = ["analyze.py", "ETH", "5m", "--risk-pct", "1", "--account-equity", "1000"]
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
        payload = json.loads(rendered.split("----- JSON -----\n", 1)[1])
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["asset_class"], "crypto_perpetual")
        self.assertEqual(payload["instrument"]["symbol"], "ETH-USDT-SWAP")
        self.assertEqual(payload["profile_name"], "balanced")
        self.assertFalse(payload["can_form_direction"])
        self.assertFalse(payload["can_size"])
        self.assertTrue(payload["no_trade"])
        self.assertEqual(payload["data_quality"]["status"], "NO_TRADE")
        self.assertIsNone(payload["bias_score"])
        self.assertIsNone(payload["bias"])
        self.assertIsNone(payload["resonance"])
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["execution_assumptions"]["sizing"], [])
        self.assertNotIn("**候选情景（", rendered)

    def test_alert_closed_data_failure_returns_nonzero(self):
        original_argv = sys.argv
        original_price, original_candles = alert.pc.okx_price, alert.pc.okx_candles
        alert.pc.okx_price = lambda *_: {
            "last": 99.0, "chg24h_pct": -1.0, "timestamp": alert.pc.now_ms(), "freshness_ok": True,
        }

        def failed_candles(_sym, _bar, _limit, errors):
            errors.append("OKX candles: timeout")
            return None

        alert.pc.okx_candles = failed_candles
        sys.argv = ["alert.py", "ETH", "100", "110", "--confirm-closed", "5m"]
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                code = alert.main()
        finally:
            sys.argv, alert.pc.okx_price, alert.pc.okx_candles = original_argv, original_price, original_candles
        self.assertEqual(code, 1)
        self.assertIn("确认数据不可用", output.getvalue())

    def test_scan_uses_no_trade_for_missing_core_derivatives(self):
        originals = {
            "price": scan.pc.okx_price, "candles": scan.pc.okx_candles,
            "derivs": scan.pc.bn_derivs, "depth": scan.pc.okx_depth_imbalance,
            "okx_funding": scan.pc.okx_funding, "bybit": scan.pc.bybit_funding,
            "argv": sys.argv,
        }
        scan.pc.okx_price = lambda *_: {
            "last": 119.9, "chg24h_pct": 1.0, "timestamp": scan.pc.now_ms(), "freshness_ok": True,
        }
        scan.pc.okx_candles = lambda *_: closed_candles()
        scan.pc.bn_derivs = lambda *_: {}
        scan.pc.okx_depth_imbalance = lambda *_: {"ratio": 1.0, "freshness_ok": True}
        scan.pc.okx_funding = lambda *_: {"rate": 0.0, "interval_hours": 8.0, "freshness_ok": True}
        scan.pc.bybit_funding = lambda *_: {"rate": 0.0, "interval_hours": 8.0, "freshness_ok": True}
        sys.argv = ["scan.py", "ETH", "5m"]
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                scan.main()
        finally:
            sys.argv = originals["argv"]
            scan.pc.okx_price = originals["price"]
            scan.pc.okx_candles = originals["candles"]
            scan.pc.bn_derivs = originals["derivs"]
            scan.pc.okx_depth_imbalance = originals["depth"]
            scan.pc.okx_funding = originals["okx_funding"]
            scan.pc.bybit_funding = originals["bybit"]
        rendered = output.getvalue()
        self.assertIn("| — | ETH | NO_TRADE |", rendered)
        self.assertNotIn("| — | ETH | CAUTION |", rendered)


if __name__ == "__main__":
    unittest.main()
