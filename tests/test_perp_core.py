import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import perp_core as pc  # noqa: E402


class PerpCoreTests(unittest.TestCase):
    def test_okx_candles_discards_open_bar_and_keeps_metadata(self):
        original_get = pc.get
        pc.get = lambda _url: ({"data": [
            ["300", "12", "13", "11", "12.5", "9", "0", "0", "0"],  # newest, open
            ["200", "11", "12", "10", "11.5", "8", "0", "0", "1"],
            ["100", "10", "11", "9", "10.5", "7", "0", "0", "1"],
        ]}, None)
        try:
            errors = []
            candles = pc.okx_candles("ETH", "5m", 3, errors)
        finally:
            pc.get = original_get

        self.assertEqual(errors, [])
        self.assertEqual(candles["timestamps"], [100, 200])
        self.assertEqual(candles["closes"], [10.5, 11.5])
        self.assertEqual(candles["confirmed"], [True, True])
        self.assertEqual(candles["meta"]["dropped_unconfirmed"], 1)
        self.assertEqual(candles["meta"]["last_confirmed_ts"], 200)

    def test_missing_funding_is_not_rendered_as_zero(self):
        rows, _, _ = pc.signal_rows(100.0, None, {})
        self.assertEqual(rows[0][0], "资金费率")
        self.assertEqual(rows[0][1], "—")
        self.assertEqual(rows[0][2], "—")

    def test_data_quality_requires_every_mtf_and_primary_derivative(self):
        price = {"last": 100.0}
        levels = {"candles": 40, "last_candle_confirmed": True, "last_candle_ts": 1}
        deriv = {
            "funding_rate_8h": 0.0,
            "oi_usd": 1.0,
            "global_ls": {"ratio": 1.0},
            "top_position": {"ratio": 1.0},
            "taker_buysell": {"last": 1.0},
            "top_account": {"ratio": 1.0},
        }
        full_mtf = [("5m", 1, 50.0, 1.0), ("15m", 1, 50.0, 1.0), ("1H", 1, 50.0, 1.0), ("4H", 1, 50.0, 1.0)]
        ready = pc.assess_data_quality(price, levels, deriv, full_mtf, depth={"ratio": 1.0}, okx_funding=0.0, bybit_funding_rate=0.0)
        self.assertEqual(ready["status"], "READY")

        partial_mtf = list(full_mtf)
        partial_mtf[1] = ("15m", None, None, None)
        blocked = pc.assess_data_quality(price, levels, deriv, partial_mtf, depth={"ratio": 1.0}, okx_funding=0.0, bybit_funding_rate=0.0)
        self.assertEqual(blocked["status"], "NO_TRADE")
        self.assertIn("15m已收盘多周期", blocked["core_missing"])

        deriv["global_ls"] = {"ratio": None}
        incomplete_ratio = pc.assess_data_quality(price, levels, deriv, full_mtf, depth={"ratio": 1.0}, okx_funding=0.0, bybit_funding_rate=0.0)
        self.assertEqual(incomplete_ratio["status"], "NO_TRADE")
        self.assertIn("Binance全站账户比", incomplete_ratio["core_missing"])

    def test_level_confirmation_uses_closed_sequence(self):
        self.assertEqual(pc.level_confirmation([101, 99, 98], 100, 110, 2), "breakdown")
        self.assertEqual(pc.level_confirmation([109, 111], 100, 110, 1), "breakout")
        self.assertIsNone(pc.level_confirmation([99, 101], 100, 110, 2))

    def test_profile_order_is_explicit(self):
        self.assertEqual(pc.profile_config("conservative")["confirmed_closes"], 2)
        self.assertEqual(pc.profile_config("balanced")["confirmed_closes"], 1)
        self.assertEqual(pc.profile_config("active")["risk_fraction"], 1.0)


if __name__ == "__main__":
    unittest.main()
