import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import perp_core as pc  # noqa: E402


class PerpCoreTests(unittest.TestCase):
    def test_freshness_rejects_far_future_timestamp(self):
        current = 1_000_000
        self.assertFalse(pc.freshness(current + 120_001, 60_000, current_ms=current)["freshness_ok"])
        self.assertTrue(pc.freshness(current + 120_000, 60_000, current_ms=current)["freshness_ok"])

    def test_okx_candles_discards_open_bar_and_keeps_metadata(self):
        interval = pc.BAR_INTERVAL_MS["5m"]
        current_open = pc.now_ms() // interval * interval
        original_get = pc.get
        pc.get = lambda _url: ({"data": [
            [str(current_open), "12", "13", "11", "12.5", "9", "0", "0", "0"],
            [str(current_open - interval), "11", "12", "10", "11.5", "8", "0", "0", "1"],
            [str(current_open - 2 * interval), "10", "11", "9", "10.5", "7", "0", "0", "1"],
        ]}, None)
        try:
            errors = []
            candles = pc.okx_candles("ETH", "5m", 3, errors)
        finally:
            pc.get = original_get

        self.assertEqual(errors, [])
        self.assertEqual(candles["timestamps"], [current_open - 2 * interval, current_open - interval])
        self.assertEqual(candles["closes"], [10.5, 11.5])
        self.assertEqual(candles["confirmed"], [True, True])
        self.assertEqual(candles["meta"]["dropped_unconfirmed"], 1)
        self.assertEqual(candles["meta"]["last_confirmed_ts"], current_open - interval)
        self.assertTrue(candles["meta"]["continuity_ok"])
        self.assertTrue(candles["meta"]["freshness_ok"])

    def test_missing_funding_is_not_rendered_as_zero(self):
        rows, _, _ = pc.signal_rows(100.0, None, {})
        self.assertEqual(rows[0][0], "资金费率")
        self.assertEqual(rows[0][1], "—")
        self.assertEqual(rows[0][2], "—")

    def test_data_quality_requires_every_mtf_and_primary_derivative(self):
        now = pc.now_ms()
        valid_meta = {"continuity_ok": True, "freshness_ok": True, "last_confirmed_close_ts": now}
        price = {"last": 100.0, "timestamp": now, "freshness_ok": True}
        levels = {"candles": 40, "last_candle_confirmed": True, "last_candle_ts": now,
                  "candle_meta": valid_meta}
        deriv = {
            "funding_rate": 0.0,
            "funding_interval_hours": 8.0,
            "funding_rate_8h": 0.0,
            "premium_freshness_ok": True,
            "oi_usd": 1.0,
            "oi_freshness_ok": True,
            "global_ls": {"ratio": 1.0, "freshness_ok": True},
            "top_position": {"ratio": 1.0, "freshness_ok": True},
            "taker_buysell": {"last": 1.0, "freshness_ok": True},
            "top_account": {"ratio": 1.0, "freshness_ok": True},
        }
        full_mtf = [("5m", 1, 50.0, 1.0, valid_meta), ("15m", 1, 50.0, 1.0, valid_meta),
                    ("1H", 1, 50.0, 1.0, valid_meta), ("4H", 1, 50.0, 1.0, valid_meta)]
        funding = {"rate": 0.0, "interval_hours": 8.0, "freshness_ok": True}
        ready = pc.assess_data_quality(price, levels, deriv, full_mtf,
                                       depth={"ratio": 1.0, "freshness_ok": True},
                                       okx_funding=funding, bybit_funding_rate=funding)
        self.assertEqual(ready["status"], "READY")

        partial_mtf = list(full_mtf)
        partial_mtf[1] = ("15m", None, None, None, {})
        blocked = pc.assess_data_quality(price, levels, deriv, partial_mtf,
                                         depth={"ratio": 1.0, "freshness_ok": True},
                                         okx_funding=funding, bybit_funding_rate=funding)
        self.assertEqual(blocked["status"], "NO_TRADE")
        self.assertIn("15m已收盘多周期", blocked["core_missing"])

        deriv["global_ls"] = {"ratio": None, "freshness_ok": True}
        incomplete_ratio = pc.assess_data_quality(price, levels, deriv, full_mtf,
                                                  depth={"ratio": 1.0, "freshness_ok": True},
                                                  okx_funding=funding, bybit_funding_rate=funding)
        self.assertEqual(incomplete_ratio["status"], "NO_TRADE")
        self.assertIn("Binance全站账户比", incomplete_ratio["core_missing"])

        deriv["global_ls"] = {"ratio": 1.0, "freshness_ok": True}
        stale_levels = {**levels, "candle_meta": {**valid_meta, "freshness_ok": False}}
        stale = pc.assess_data_quality(price, stale_levels, deriv, full_mtf,
                                       depth={"ratio": 1.0, "freshness_ok": True},
                                       okx_funding=funding, bybit_funding_rate=funding)
        self.assertEqual(stale["status"], "NO_TRADE")
        self.assertIn("主周期K线时效", stale["core_missing"])

    def test_level_confirmation_uses_closed_sequence(self):
        self.assertEqual(pc.level_confirmation([101, 99, 98], 100, 110, 2), "breakdown")
        self.assertEqual(pc.level_confirmation([109, 111], 100, 110, 1), "breakout")
        self.assertIsNone(pc.level_confirmation([99, 101], 100, 110, 2))
        self.assertIsNone(pc.level_confirmation([100], 100, 110, 1))
        self.assertIsNone(pc.level_confirmation([110], 100, 110, 1))

    def test_profile_order_is_explicit(self):
        self.assertEqual(pc.profile_config("conservative")["confirmed_closes"], 2)
        self.assertEqual(pc.profile_config("balanced")["confirmed_closes"], 1)
        self.assertEqual(pc.profile_config("active")["risk_fraction"], 1.0)
        self.assertEqual(pc.profile_config("conservative")["min_signal_score"], 3.0)
        self.assertEqual(pc.profile_config("active")["min_signal_score"], 0.25)

    def test_flat_rsi_is_neutral(self):
        self.assertEqual(pc.rsi([100.0] * 30), 50.0)

    def test_build_levels_preserves_micro_price_ema_precision(self):
        closes = [0.00001000 + index * 0.00000001 for index in range(40)]
        candles = {
            "timestamps": list(range(40)), "confirmed": [True] * 40,
            "opens": closes, "highs": [value + 1e-9 for value in closes],
            "lows": [value - 1e-9 for value in closes], "closes": closes,
            "volumes": [1.0] * 40, "meta": {},
        }
        levels = pc.build_levels(candles)
        self.assertGreater(levels["ema9"], levels["ema21"])
        self.assertNotEqual(levels["ema9"], 0.0)
        self.assertNotEqual(pc.format_price(closes[-1]), "0.00")

    def test_bad_ticker_field_degrades_instead_of_raising(self):
        original_get = pc.get
        pc.get = lambda _url: ({"data": [{"last": None, "open24h": "100", "ts": pc.now_ms()}]}, None)
        try:
            errors = []
            self.assertIsNone(pc.okx_price("ETH", errors))
        finally:
            pc.get = original_get
        self.assertIn("OKX ticker: invalid last price", errors)

    def test_binance_funding_interval_is_normalized(self):
        timestamp = pc.now_ms()

        def fake_get(url):
            if "fundingInfo" in url:
                return ([{"symbol": "ETHUSDT", "fundingIntervalHours": 4}], None)
            if "premiumIndex" in url:
                return ({"lastFundingRate": "0.0001", "markPrice": "100", "indexPrice": "100",
                         "time": timestamp, "nextFundingTime": timestamp + 4 * 3_600_000}, None)
            if "openInterestHist" in url:
                return ([{"sumOpenInterest": "10", "sumOpenInterestValue": "1000", "timestamp": timestamp}], None)
            if "takerlongshortRatio" in url:
                return ([{"buySellRatio": "1", "timestamp": timestamp}], None)
            if "LongShort" in url or "longShort" in url:
                return ([{"longShortRatio": "1", "longAccount": "0.5", "shortAccount": "0.5",
                          "timestamp": timestamp}], None)
            if "ticker/24hr" in url:
                return ({"lastPrice": "100"}, None)
            raise AssertionError(url)

        original_get = pc.get
        pc.get = fake_get
        try:
            errors = []
            deriv = pc.bn_derivs("ETH", "5m", errors)
        finally:
            pc.get = original_get
        self.assertEqual(errors, [])
        self.assertEqual(deriv["funding_interval_hours"], 4.0)
        self.assertAlmostEqual(deriv["funding_rate_8h_equiv"], 0.0002)
        self.assertAlmostEqual(deriv["funding_apr_pct"], 21.9)


if __name__ == "__main__":
    unittest.main()
