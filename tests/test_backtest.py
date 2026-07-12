import math
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest as bt  # noqa: E402
import perp_core as pc  # noqa: E402


def run(rows, **overrides):
    options = {
        "profile": "balanced",
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
        "stop_atr": 1.2,
        "target_r": 2.0,
        "max_hold": 48,
    }
    options.update(overrides)
    return bt.run(rows, **options)


class ValidationTests(unittest.TestCase):
    def test_rejects_non_finite_impossible_ohlc_and_bad_time_order(self):
        valid = [
            {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp": "t1", "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp": "t2", "open": 100, "high": 101, "low": 99, "close": 100},
        ]
        bad_nan = [dict(row) for row in valid]
        bad_nan[1]["open"] = math.nan
        with self.assertRaisesRegex(ValueError, "有限数字"):
            run(bad_nan)

        bad_ohlc = [dict(row) for row in valid]
        bad_ohlc[1].update({"open": 100, "high": 99, "low": 98, "close": 100})
        with self.assertRaisesRegex(ValueError, "high"):
            run(bad_ohlc)

        bad_time = [dict(row) for row in valid]
        bad_time[2]["timestamp"] = "t1"
        with self.assertRaisesRegex(ValueError, "严格递增"):
            run(bad_time)

    def test_rejects_invalid_parameters_and_accepts_csv_style_numeric_side(self):
        rows = [
            {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100, "side": "1.0"},
            {"timestamp": "t1", "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp": "t2", "open": 100, "high": 101, "low": 99, "close": 100},
        ]
        with self.assertRaisesRegex(ValueError, "fee_bps"):
            run(rows, fee_bps=-1)
        with self.assertRaisesRegex(ValueError, "max_hold"):
            run(rows, max_hold=0)
        self.assertEqual(bt.normalize_rows(rows)[0]["side"], 1)


class ExecutionTests(unittest.TestCase):
    def test_gap_through_existing_stop_uses_open_not_theoretical_stop(self):
        rows = [
            {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100,
             "side": 1, "signal_score": 3, "stop": 95, "target": 120},
            {"timestamp": "t1", "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp": "t2", "open": 90, "high": 92, "low": 89, "close": 91},
        ]
        trade = run(rows)["trades"][0]
        self.assertEqual(trade["reason"], "stop_gap")
        self.assertEqual(trade["exit_reference_price"], 90)
        self.assertAlmostEqual(trade["gross_return"], -0.10)

    def test_entry_is_cancelled_when_next_open_is_beyond_user_stop(self):
        rows = [
            {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100,
             "side": 1, "signal_score": 3, "stop": 95, "target": 120},
            {"timestamp": "t1", "open": 90, "high": 92, "low": 89, "close": 91},
            {"timestamp": "t2", "open": 91, "high": 92, "low": 90, "close": 91},
        ]
        result = run(rows)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["skipped_entries"][0]["reason"], "open_beyond_user_stop")
        self.assertEqual(result["skipped_entries"][0]["user_stop"], 95)

    def test_mark_to_market_drawdown_and_excursions_use_each_bar(self):
        rows = [
            {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100,
             "side": 1, "signal_score": 3, "stop": 1, "target": 200},
            {"timestamp": "t1", "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp": "t2", "open": 100, "high": 101, "low": 10, "close": 20},
            {"timestamp": "t3", "open": 20, "high": 106, "low": 19, "close": 105},
        ]
        result = run(rows)
        self.assertAlmostEqual(result["summary"]["mark_to_market_max_drawdown_pct"], 80.0)
        self.assertAlmostEqual(result["summary"]["closed_trade_max_drawdown_pct"], 0.0)
        self.assertAlmostEqual(result["trades"][0]["mae_pct"], -90.0)
        self.assertAlmostEqual(result["trades"][0]["mfe_pct"], 6.0)

    def test_fees_use_entry_and_exit_notional_and_funding_is_separate(self):
        rows = [
            {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100,
             "side": 1, "signal_score": 3, "stop": 90, "target": 110},
            {"timestamp": "t1", "open": 100, "high": 105, "low": 99, "close": 100, "funding_rate": 0.001},
            {"timestamp": "t2", "open": 100, "high": 111, "low": 99, "close": 110, "funding_rate": 0.5},
        ]
        trade = run(rows, fee_bps=100)["trades"][0]
        self.assertAlmostEqual(trade["entry_fee_return"], 0.01)
        self.assertAlmostEqual(trade["exit_fee_return"], 0.011)
        self.assertAlmostEqual(trade["funding_cost_return"], 0.001)
        self.assertEqual(trade["funding_events"], 1)
        self.assertAlmostEqual(trade["cost_return"], 0.022)

    def test_signal_on_exit_bar_can_enter_at_following_open(self):
        rows = [
            {"timestamp": "t0", "open": 100, "high": 100.5, "low": 99.5, "close": 100,
             "side": 1, "signal_score": 3, "stop": 99, "target": 101},
            {"timestamp": "t1", "open": 100, "high": 102, "low": 99.5, "close": 101,
             "side": -1, "signal_score": 3, "stop": 103, "target": 95},
            {"timestamp": "t2", "open": 100, "high": 100.5, "low": 94, "close": 95},
        ]
        result = run(rows)
        self.assertEqual([trade["side"] for trade in result["trades"]], ["long", "short"])
        self.assertEqual(result["trades"][1]["entry_at"], "t2")

    def test_result_echoes_live_profile_mapping_and_execution_config(self):
        rows = [
            {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp": "t1", "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp": "t2", "open": 100, "high": 101, "low": 99, "close": 100},
        ]
        result = run(rows, profile="active", fee_bps=4, slippage_bps=2, stop_atr=1.5, target_r=3, max_hold=12)
        self.assertEqual(result["config"]["profile_mapping"], pc.profile_config("active"))
        self.assertEqual(result["config"]["min_signal_score"], pc.profile_config("active")["min_signal_score"])
        self.assertEqual(result["config"]["fee_bps_each_way"], 4)
        self.assertEqual(result["config"]["max_hold_bars"], 12)


if __name__ == "__main__":
    unittest.main()
