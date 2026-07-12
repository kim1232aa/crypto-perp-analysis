#!/usr/bin/env python3
"""
perp_core :: shared data-fetch + indicator + signal-tagging library.
Used by analyze.py (detailed single-symbol), scan.py (batch), alert.py (monitor).
Stdlib only. NEVER fabricates: every fetch returns (data, error); callers surface errors.
"""
import json
import math
import time
import urllib.request


# Kept in the shared module so the analysis report and the monitor agree on
# what a "confirmed" setup means. A profile changes presentation and the
# suggested fraction of a user-supplied risk budget; it never turns a live tick
# into a completed candle or a guaranteed trade.
PROFILES = {
    "conservative": {
        "confirmed_closes": 2,
        "risk_fraction": 0.50,
        "min_signal_score": 3.0,
        "label": "等待两根已收盘K确认，回踩优先",
    },
    "balanced": {
        "confirmed_closes": 1,
        "risk_fraction": 0.75,
        "min_signal_score": 1.0,
        "label": "一根已收盘K确认，回踩/突破均为候选",
    },
    "active": {
        "confirmed_closes": 1,
        "risk_fraction": 1.00,
        "min_signal_score": 0.25,
        "label": "一根已收盘K确认后关注动量，仍不以实时越界成交",
    },
}

BAR_INTERVAL_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "1H": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "2H": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "4H": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "6H": 6 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "12H": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "1D": 24 * 60 * 60_000,
}


def profile_config(name):
    """Return a copy of a supported execution-profile configuration."""
    key = (name or "balanced").lower()
    if key not in PROFILES:
        raise ValueError(f"unknown profile {name!r}; choose one of {', '.join(PROFILES)}")
    return {"name": key, **PROFILES[key]}

def get(url):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
              "User-Agent": "Mozilla/5.0 (perp-analysis)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def num(x):
    try:
        value = float(x)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def integer(x):
    value = num(x)
    return int(value) if value is not None else None


def pct(a, b):
    return None if a is None or b in (None, 0) else (a - b) / b * 100.0


def now_ms():
    return int(time.time() * 1000)


def freshness(timestamp_ms, max_age_ms, current_ms=None):
    """Return timestamp age metadata without silently accepting missing clocks."""
    timestamp_ms = integer(timestamp_ms)
    if timestamp_ms is None:
        return {"timestamp": None, "age_ms": None, "max_age_ms": max_age_ms, "freshness_ok": False}
    current_ms = now_ms() if current_ms is None else current_ms
    future_skew = timestamp_ms - current_ms
    age = max(0, current_ms - timestamp_ms)
    return {"timestamp": timestamp_ms, "age_ms": age, "max_age_ms": max_age_ms,
            "freshness_ok": future_skew <= 120_000 and age <= max_age_ms}


def format_price(value, significant=6, max_decimals=12):
    """Format prices adaptively; do not collapse micro-priced contracts to 0.00."""
    value = num(value)
    if value is None:
        return "—"
    if value == 0:
        return "0"
    magnitude = math.floor(math.log10(abs(value)))
    decimals = max(0, min(max_decimals, significant - 1 - magnitude))
    return f"{value:.{decimals}f}"

# ---------------- indicators ----------------
def ema(vals, period):
    if not vals: return None
    k = 2.0 / (period + 1); e = vals[0]
    for v in vals[1:]: e = v * k + e * (1 - k)
    return e
def rsi(closes, period=14):
    if len(closes) < period + 1: return None
    g = l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i-1]; g += max(d, 0); l += max(-d, 0)
    ag, al = g / period, l / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i-1]
        ag = (ag * (period-1) + max(d, 0)) / period
        al = (al * (period-1) + max(-d, 0)) / period
    if al == 0 and ag == 0: return 50.0
    if al == 0: return 100.0
    return 100 - 100 / (1 + ag / al)
def atr(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 1: return None
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, n)]
    a = sum(trs[:period]) / period
    for i in range(period, len(trs)): a = (a * (period-1) + trs[i]) / period
    return a
def divergence(closes):
    """Heuristic 2-segment RSI divergence over last 20 closes. Returns text or None."""
    if len(closes) < 20: return None
    tail = closes[-20:]; mid = 10
    h1i = max(range(mid), key=lambda i: tail[i]); h2i = mid + max(range(mid), key=lambda i: tail[mid+i])
    l1i = min(range(mid), key=lambda i: tail[i]); l2i = mid + min(range(mid), key=lambda i: tail[mid+i])
    base = closes[:-20]
    def rsi_at(idx): return rsi(base + tail[:idx+1])
    r_h1, r_h2 = rsi_at(h1i), rsi_at(h2i); r_l1, r_l2 = rsi_at(l1i), rsi_at(l2i)
    if None not in (r_h1, r_h2) and tail[h2i] > tail[h1i] and r_h2 < r_h1 - 2:
        return "顶背离(价创新高RSI走弱)→偏空"
    if None not in (r_l1, r_l2) and tail[l2i] < tail[l1i] and r_l2 > r_l1 + 2:
        return "底背离(价创新低RSI走强)→偏多"
    return None
def wtrend(series):
    s = [x for x in series if x is not None]
    if len(s) < 2: return 0
    d = s[-1] - s[0]; base = abs(s[0]) or 1
    return 1 if d/base > 0.0005 else -1 if d/base < -0.0005 else 0

# ---------------- OKX fetchers ----------------
def _okx_data(payload, source, errors):
    if not isinstance(payload, dict):
        errors.append(f"{source}: malformed response")
        return None
    code = payload.get("code")
    if code not in (None, 0, "0"):
        errors.append(f"{source}: code={code} {payload.get('msg', '')}".strip())
        return None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        errors.append(f"{source}: empty response")
        return None
    return data


def okx_price(sym, errors):
    d, e = get(f"https://www.okx.com/api/v5/market/ticker?instId={sym}-USDT-SWAP")
    if e:
        errors.append(f"OKX ticker: {e}")
        return None
    data = _okx_data(d, "OKX ticker", errors)
    if not data or not isinstance(data[0], dict):
        if data:
            errors.append("OKX ticker: malformed row")
        return None
    x = data[0]
    last = num(x.get("last"))
    if last is None or last <= 0:
        errors.append("OKX ticker: invalid last price")
        return None
    timing = freshness(x.get("ts"), 5 * 60_000)
    return {
        "last": last,
        "open24h": num(x.get("open24h")),
        "high24h": num(x.get("high24h")),
        "low24h": num(x.get("low24h")),
        "chg24h_pct": pct(last, num(x.get("open24h"))),
        "bid": num(x.get("bidPx")),
        "ask": num(x.get("askPx")),
        **timing,
    }


def okx_candles(sym, bar, limit, errors):
    """Fetch closed OKX candles and retain timing/confirmation metadata.

    The last row in an OKX candles response can be an unfinished candle. Its
    OHLC values can change, so it must not feed indicators, levels, alerts or a
    backtest-style decision. ``meta`` makes the discarded rows visible to JSON
    consumers instead of silently treating the response as fixed history.
    """
    d, e = get(f"https://www.okx.com/api/v5/market/candles?instId={sym}-USDT-SWAP&bar={bar}&limit={limit}")
    if e:
        errors.append(f"OKX candles {bar}: {e}")
        return None
    data = _okx_data(d, f"OKX candles {bar}", errors)
    if not data:
        return None

    raw = list(reversed(data))  # chronological; OKX returns newest first
    closed, malformed, dropped = [], 0, 0
    last_response_ts = None
    for r in raw:
        try:
            ts = int(r[0])
            last_response_ts = ts
            confirmed = str(r[8]) == "1"
            if not confirmed:
                dropped += 1
                continue
            candle = {
                "timestamp": ts,
                "confirmed": confirmed,
                "open": num(r[1]),
                "high": num(r[2]),
                "low": num(r[3]),
                "close": num(r[4]),
                "volume": num(r[5]),
            }
            ohlc = (candle["open"], candle["high"], candle["low"], candle["close"])
            if (None in ohlc or any(value <= 0 for value in ohlc)
                    or candle["high"] < max(candle["open"], candle["close"])
                    or candle["low"] > min(candle["open"], candle["close"])
                    or candle["high"] < candle["low"]):
                malformed += 1
                continue
            closed.append(candle)
        except (IndexError, TypeError, ValueError):
            malformed += 1

    if not closed:
        errors.append(f"OKX candles {bar}: no confirmed candles")
        return None

    response_order_ok = all(
        closed[index]["timestamp"] < closed[index + 1]["timestamp"]
        for index in range(len(closed) - 1)
    )
    if not response_order_ok:
        errors.append(f"OKX candles {bar}: rows not strictly chronological")
    closed.sort(key=lambda candle: candle["timestamp"])
    unique, seen, duplicate_count = [], set(), 0
    for candle in closed:
        if candle["timestamp"] in seen:
            duplicate_count += 1
            continue
        seen.add(candle["timestamp"])
        unique.append(candle)
    closed = unique

    interval_ms = BAR_INTERVAL_MS.get(bar)
    gaps = []
    irregular = []
    if interval_ms:
        for previous, current in zip(closed, closed[1:]):
            difference = current["timestamp"] - previous["timestamp"]
            if difference > interval_ms:
                gaps.append(difference)
            elif difference != interval_ms:
                irregular.append(difference)
    continuity_ok = bool(interval_ms) and response_order_ok and not duplicate_count and not gaps and not irregular
    if duplicate_count:
        errors.append(f"OKX candles {bar}: skipped {duplicate_count} duplicate row(s)")
    if gaps or irregular:
        errors.append(f"OKX candles {bar}: discontinuous timestamps")
    if malformed:
        errors.append(f"OKX candles {bar}: skipped {malformed} malformed row(s)")

    last_confirmed_ts = closed[-1]["timestamp"]
    close_timestamp = last_confirmed_ts + interval_ms if interval_ms else None
    timing = freshness(close_timestamp, interval_ms + 120_000 if interval_ms else 0)

    return {
        "timestamps": [x["timestamp"] for x in closed],
        "confirmed": [x["confirmed"] for x in closed],
        "opens": [x["open"] for x in closed],
        "highs": [x["high"] for x in closed],
        "lows": [x["low"] for x in closed],
        "closes": [x["close"] for x in closed],
        "volumes": [x["volume"] for x in closed],
        "meta": {
            "bar": bar,
            "interval_ms": interval_ms,
            "raw_count": len(raw),
            "confirmed_count": len(closed),
            "dropped_unconfirmed": dropped,
            "malformed_count": malformed,
            "duplicate_count": duplicate_count,
            "gap_count": len(gaps),
            "irregular_interval_count": len(irregular),
            "continuity_ok": continuity_ok,
            "last_confirmed_ts": last_confirmed_ts,
            "last_confirmed_close_ts": close_timestamp,
            "last_response_ts": last_response_ts,
            **timing,
        },
    }


def okx_funding(sym, errors):
    d, e = get(f"https://www.okx.com/api/v5/public/funding-rate?instId={sym}-USDT-SWAP")
    if e:
        errors.append(f"OKX funding: {e}")
        return None
    data = _okx_data(d, "OKX funding", errors)
    if not data or not isinstance(data[0], dict):
        if data:
            errors.append("OKX funding: malformed row")
        return None
    row = data[0]
    rate = num(row.get("fundingRate"))
    funding_time = integer(row.get("fundingTime"))
    next_funding_time = integer(row.get("nextFundingTime"))
    interval_hours = None
    if funding_time is not None and next_funding_time is not None and next_funding_time > funding_time:
        interval_hours = (next_funding_time - funding_time) / 3_600_000
    if rate is None:
        errors.append("OKX funding: invalid fundingRate")
        return None
    timing = freshness(row.get("ts"), 5 * 60_000)
    return {
        "rate": rate,
        "interval_hours": interval_hours,
        "rate_8h_equiv": rate * 8 / interval_hours if interval_hours else None,
        "funding_time": funding_time,
        "next_funding_time": next_funding_time,
        "observed_at": now_ms(),
        **timing,
    }


def okx_depth_imbalance(sym, errors, band=0.005):
    d, e = get(f"https://www.okx.com/api/v5/market/books?instId={sym}-USDT-SWAP&sz=50")
    if e:
        errors.append(f"OKX depth: {e}")
        return None
    data = _okx_data(d, "OKX depth", errors)
    if not data or not isinstance(data[0], dict):
        if data:
            errors.append("OKX depth: malformed row")
        return None
    row = data[0]
    bids, asks = [], []
    for raw_level, target in ((row.get("bids", []), bids), (row.get("asks", []), asks)):
        if not isinstance(raw_level, list):
            continue
        for level in raw_level:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue
            price, size = num(level[0]), num(level[1])
            if price is not None and price > 0 and size is not None and size >= 0:
                target.append((price, size))
    if not bids or not asks:
        errors.append("OKX depth: no valid bid/ask levels")
        return None
    mid = (bids[0][0] + asks[0][0]) / 2
    lo, hi = mid * (1 - band), mid * (1 + band)
    bidv = sum(size for price, size in bids if price >= lo)
    askv = sum(size for price, size in asks if price <= hi)
    timing = freshness(row.get("ts"), 5 * 60_000)
    return {"ratio": bidv / askv if askv else None, "bidv": bidv, "askv": askv,
            "band": band, **timing}

def build_levels(cd):
    """cd = okx_candles dict -> structure + indicators."""
    if not cd or len(cd.get("closes", [])) < 30: return None
    c, h, l = cd["closes"], cd["highs"], cd["lows"]; n = len(c)
    return {"candles": n,
            "swing_high_30": max(h[-30:]), "swing_low_30": min(l[-30:]),
            "swing_high_12": max(h[-12:]), "swing_low_12": min(l[-12:]),
            # Warm up the EMA with the complete returned closed history rather
            # than restarting EMA21 from only 30 observations.
            "ema9": ema(c, 9), "ema21": ema(c, 21),
            "rsi14": rsi(c), "atr14": atr(h, l, c),
            "divergence": divergence(c),
            "price_chg_window_pct": pct(c[-1], c[-13]) if n >= 13 else None,
            "recent_closes": c[-12:],
            "last_close": c[-1],
            "last_candle_ts": cd["timestamps"][-1],
            "last_candle_confirmed": bool(cd["confirmed"][-1]),
            "candle_meta": cd.get("meta", {}),
    }

# ---------------- Binance derivatives ----------------
def bn_derivs(sym, period, errors):
    B = "https://fapi.binance.com"; s = f"{sym}USDT"; out = {}

    funding_interval = None
    funding_info, e = get(f"{B}/fapi/v1/fundingInfo")
    if e:
        errors.append(f"BN fundingInfo: {e}")
    elif isinstance(funding_info, list):
        adjusted = next(
            (row for row in funding_info if isinstance(row, dict) and row.get("symbol") == s),
            None,
        )
        funding_interval = num((adjusted or {}).get("fundingIntervalHours")) if adjusted else 8.0
        if funding_interval is None or funding_interval <= 0:
            errors.append("BN fundingInfo: invalid fundingIntervalHours")
            funding_interval = None
    else:
        message = funding_info.get("msg") if isinstance(funding_info, dict) else "malformed response"
        errors.append(f"BN fundingInfo: {message}")

    pi, e = get(f"{B}/fapi/v1/premiumIndex?symbol={s}")
    if e:
        errors.append(f"BN premiumIndex: {e}")
    elif isinstance(pi, dict) and pi.get("code") is None:
        mark, idx, fr = num(pi.get("markPrice")), num(pi.get("indexPrice")), num(pi.get("lastFundingRate"))
        premium_timing = freshness(pi.get("time"), 5 * 60_000)
        if fr is None:
            errors.append("BN premiumIndex: invalid lastFundingRate")
        out.update({
            "funding_rate": fr,
            "funding_interval_hours": funding_interval,
            "funding_rate_8h_equiv": fr * 8 / funding_interval if fr is not None and funding_interval else None,
            # Compatibility alias: this is explicitly the 8-hour-equivalent rate.
            "funding_rate_8h": fr * 8 / funding_interval if fr is not None and funding_interval else None,
            "funding_apr_pct": None if fr is None or not funding_interval else fr * (24 / funding_interval) * 365 * 100,
            "mark": mark,
            "index": idx,
            "basis_pct": pct(mark, idx),
            "premium_timestamp": premium_timing["timestamp"],
            "premium_age_ms": premium_timing["age_ms"],
            "premium_freshness_ok": premium_timing["freshness_ok"],
            "next_funding_time": integer(pi.get("nextFundingTime")),
        })
    else:
        message = pi.get("msg") if isinstance(pi, dict) else "malformed response"
        errors.append(f"BN premiumIndex: {message}")

    oi, e = get(f"{B}/futures/data/openInterestHist?symbol={s}&period={period}&limit=12")
    if e:
        errors.append(f"BN OI: {e}")
    elif isinstance(oi, list) and oi:
        valid_oi = []
        for row in oi:
            if not isinstance(row, dict):
                continue
            amount = num(row.get("sumOpenInterest"))
            value = num(row.get("sumOpenInterestValue"))
            timestamp = integer(row.get("timestamp"))
            if amount is None or value is None or timestamp is None:
                continue
            valid_oi.append((timestamp, amount, value))
        valid_oi.sort()
        if valid_oi:
            series = [row[1] for row in valid_oi]
            interval_ms = BAR_INTERVAL_MS.get(period)
            observation_ts = valid_oi[-1][0] + interval_ms if interval_ms else valid_oi[-1][0]
            oi_timing = freshness(observation_ts, (interval_ms or 5 * 60_000) + 120_000)
            out.update({"oi_now": series[-1], "oi_usd": valid_oi[-1][2],
                        "oi_chg_window_pct": pct(series[-1], series[0]), "oi_trend": wtrend(series),
                        "oi_timestamp": valid_oi[-1][0], "oi_freshness_ok": oi_timing["freshness_ok"],
                        "oi_valid_count": len(valid_oi)})
        else:
            errors.append("BN OI: no valid rows")
    else:
        message = oi.get("msg") if isinstance(oi, dict) else "empty/malformed response"
        errors.append(f"BN OI: {message}")

    def lsb(path, tag):
        dd, ee = get(f"{B}/futures/data/{path}?symbol={s}&period={period}&limit=6")
        if ee:
            errors.append(f"BN {tag}: {ee}")
            return None
        if not (isinstance(dd, list) and dd):
            message = dd.get("msg") if isinstance(dd, dict) else "empty/malformed response"
            errors.append(f"BN {tag}: {message}")
            return None
        valid = []
        for row in dd:
            if not isinstance(row, dict):
                continue
            ratio, timestamp = num(row.get("longShortRatio")), integer(row.get("timestamp"))
            if ratio is not None and ratio >= 0 and timestamp is not None:
                valid.append((timestamp, ratio, row))
        valid.sort(key=lambda item: item[0])
        if not valid:
            errors.append(f"BN {tag}: no valid rows")
            return None
        interval_ms = BAR_INTERVAL_MS.get(period)
        timing = freshness(valid[-1][0] + (interval_ms or 0), (interval_ms or 5 * 60_000) + 120_000)
        last = valid[-1][2]
        return {"ratio": valid[-1][1], "long_pct": num(last.get("longAccount")),
                "short_pct": num(last.get("shortAccount")), "trend": wtrend([item[1] for item in valid]),
                "timestamp": valid[-1][0], "freshness_ok": timing["freshness_ok"],
                "valid_count": len(valid)}

    out["global_ls"]    = lsb("globalLongShortAccountRatio", "global L/S")
    out["top_account"]  = lsb("topLongShortAccountRatio", "top acct")
    out["top_position"] = lsb("topLongShortPositionRatio", "top pos")
    tk, e = get(f"{B}/futures/data/takerlongshortRatio?symbol={s}&period={period}&limit=6")
    if e:
        errors.append(f"BN taker: {e}")
    elif isinstance(tk, list) and tk:
        valid = []
        for row in tk:
            if not isinstance(row, dict):
                continue
            ratio, timestamp = num(row.get("buySellRatio")), integer(row.get("timestamp"))
            if ratio is not None and ratio >= 0 and timestamp is not None:
                valid.append((timestamp, ratio))
        valid.sort()
        if valid:
            series = [item[1] for item in valid]
            interval_ms = BAR_INTERVAL_MS.get(period)
            timing = freshness(valid[-1][0] + (interval_ms or 0), (interval_ms or 5 * 60_000) + 120_000)
            out["taker_buysell"] = {"last": series[-1], "series": [round(x, 3) for x in series],
                                     "trend": wtrend(series), "timestamp": valid[-1][0],
                                     "freshness_ok": timing["freshness_ok"], "valid_count": len(valid)}
        else:
            errors.append("BN taker: no valid rows")
    else:
        message = tk.get("msg") if isinstance(tk, dict) else "empty/malformed response"
        errors.append(f"BN taker: {message}")

    t24, e = get(f"{B}/fapi/v1/ticker/24hr?symbol={s}")
    if not e and isinstance(t24, dict) and t24.get("code") is None:
        out["binance_24h"] = {"last": num(t24.get("lastPrice")), "chg_pct": num(t24.get("priceChangePercent")),
                              "high": num(t24.get("highPrice")), "low": num(t24.get("lowPrice")),
                              "quote_vol_usd": num(t24.get("quoteVolume"))}
    return out


def bybit_funding(sym, errors):
    d, e = get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}USDT")
    if e:
        errors.append(f"Bybit funding: {e}")
        return None
    if not isinstance(d, dict) or d.get("retCode") not in (None, 0, "0"):
        message = d.get("retMsg") if isinstance(d, dict) else "malformed response"
        errors.append(f"Bybit funding: {message}")
        return None
    rows = (d.get("result") or {}).get("list")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        errors.append("Bybit funding: empty/malformed response")
        return None
    row = rows[0]
    rate = num(row.get("fundingRate"))
    interval_hours = num(row.get("fundingIntervalHour"))
    if rate is None:
        errors.append("Bybit funding: invalid fundingRate")
        return None
    timing = freshness(d.get("time"), 5 * 60_000)
    return {
        "rate": rate,
        "interval_hours": interval_hours,
        "rate_8h_equiv": rate * 8 / interval_hours if interval_hours and interval_hours > 0 else None,
        "next_funding_time": integer(row.get("nextFundingTime")),
        **timing,
    }


# ---------------- data quality + confirmation ----------------
def assess_data_quality(price, levels, deriv, mtf, errors=None, depth=None,
                        okx_funding=None, bybit_funding_rate=None):
    """Grade whether a directional trade claim has enough live evidence.

    The report may still show the available numbers when data is partial, but a
    missing price/closed structure/multi-timeframe/primary derivatives field
    produces ``NO_TRADE``.  This avoids converting failed API calls into a
    neutral score and a spurious trade instruction.
    """
    core_missing = []
    if not price or price.get("last") is None:
        core_missing.append("OKX现价")
    elif price.get("freshness_ok") is not True:
        core_missing.append("OKX现价时效")
    if not levels:
        core_missing.append("至少30根已收盘K线")
    elif not levels.get("last_candle_confirmed"):
        core_missing.append("最新结构K线确认")
    else:
        candle_meta = levels.get("candle_meta") or {}
        if candle_meta.get("continuity_ok") is not True:
            core_missing.append("主周期K线连续性")
        if candle_meta.get("freshness_ok") is not True:
            core_missing.append("主周期K线时效")

    expected_tfs = ["5m", "15m", "1H", "4H"]
    found = {}
    for item in mtf or []:
        if isinstance(item, dict):
            found[item.get("tf")] = (item.get("dir"), item.get("rsi"), item.get("close"), item.get("meta") or {})
        elif len(item) >= 5:
            tf, direction, rsi_value, close, meta = item[:5]
            found[tf] = (direction, rsi_value, close, meta or {})
        else:
            tf, direction, rsi_value, close = item
            found[tf] = (direction, rsi_value, close, {})
    for tf in expected_tfs:
        d, r, close, meta = found.get(tf, (None, None, None, {}))
        if d is None or r is None or close is None:
            core_missing.append(f"{tf}已收盘多周期")
            continue
        if meta.get("continuity_ok") is not True:
            core_missing.append(f"{tf}K线连续性")
        if meta.get("freshness_ok") is not True:
            core_missing.append(f"{tf}K线时效")

    deriv = deriv or {}
    primary_derivs = {
        "Binance资金费": deriv.get("funding_rate"),
        "Binance资金费周期": deriv.get("funding_interval_hours"),
        "Binance OI": deriv.get("oi_usd"),
        "Binance全站账户比": (deriv.get("global_ls") or {}).get("ratio"),
        "Binance头部持仓比": (deriv.get("top_position") or {}).get("ratio"),
        "Taker买卖比": (deriv.get("taker_buysell") or {}).get("last"),
    }
    core_missing.extend(name for name, value in primary_derivs.items() if value is None)
    freshness_fields = {
        "Binance资金费时效": deriv.get("premium_freshness_ok"),
        "Binance OI时效": deriv.get("oi_freshness_ok"),
        "Binance全站账户比时效": (deriv.get("global_ls") or {}).get("freshness_ok"),
        "Binance头部持仓比时效": (deriv.get("top_position") or {}).get("freshness_ok"),
        "Taker买卖比时效": (deriv.get("taker_buysell") or {}).get("freshness_ok"),
    }
    core_missing.extend(name for name, value in freshness_fields.items() if value is not True)

    optional_missing = []
    if not depth or depth.get("ratio") is None or depth.get("freshness_ok") is not True:
        optional_missing.append("OKX盘口")
    if (not isinstance(okx_funding, dict) or okx_funding.get("rate") is None
            or okx_funding.get("interval_hours") is None or okx_funding.get("freshness_ok") is not True):
        optional_missing.append("OKX资金费")
    if (not isinstance(bybit_funding_rate, dict) or bybit_funding_rate.get("rate") is None
            or bybit_funding_rate.get("interval_hours") is None
            or bybit_funding_rate.get("freshness_ok") is not True):
        optional_missing.append("Bybit资金费")
    if ((deriv.get("top_account") or {}).get("ratio") is None
            or (deriv.get("top_account") or {}).get("freshness_ok") is not True):
        optional_missing.append("Binance头部账户比")

    status = "NO_TRADE" if core_missing else ("CAUTION" if optional_missing else "READY")
    return {
        "status": status,
        "status_label": ("核心数据不可用" if status == "NO_TRADE" else
                         "辅助数据缺失" if status == "CAUTION" else "完整"),
        "trade_ready": status != "NO_TRADE",
        "core_missing": core_missing,
        "optional_missing": optional_missing,
        "error_count": len(errors or []),
        "confirmed_structure_candles": (levels or {}).get("candles", 0),
        "last_confirmed_candle_ts": (levels or {}).get("last_candle_ts"),
        "source_timing": {
            "okx_price_ts": (price or {}).get("timestamp"),
            "okx_structure_close_ts": ((levels or {}).get("candle_meta") or {}).get("last_confirmed_close_ts"),
            "binance_premium_ts": deriv.get("premium_timestamp"),
            "binance_oi_ts": deriv.get("oi_timestamp"),
        },
    }


def level_confirmation(closes, support, resistance, required_closes=1):
    """Classify a level only after the requested number of closed candles.

    ``None`` means there are not enough confirmed closes or no confirmed level
    break.  This intentionally differs from a live-tick *warning*.
    """
    if required_closes < 1:
        raise ValueError("required_closes must be >= 1")
    if not closes or len(closes) < required_closes:
        return None
    tail = closes[-required_closes:]
    if all(x < support for x in tail):
        return "breakdown"
    if all(x > resistance for x in tail):
        return "breakout"
    return None

# ---------------- signal tagging (returns rows + score + bias) ----------------
def _t_funding(fr):
    if fr is None: return ("—", 0)
    r = fr*100
    if r > 0.05:  return ("多头过热·追多有反噬风险", -1)
    if r >= 0.01: return ("正费率但健康", 0.5)
    if r > -0.01: return ("中性", 0)
    return ("空头付费·潜在轧空燃料", 1)
def _t_basis(bp):
    if bp is None: return ("—", 0)
    if bp > 0.1:   return ("升水过大·投机过热", -0.5)
    if bp > 0.03:  return ("升水·投机偏多", 0.5)
    if bp >= -0.03:return ("基差平·中性", 0)
    return ("贴水·现货主导/偏冷", -0.3)
def _t_oi(oitrend, pchg):
    if oitrend is None: return ("—", 0)
    up = pchg is not None and pchg > 0.03; dn = pchg is not None and pchg < -0.03
    if oitrend > 0 and up: return ("价涨仓增·多头加仓续涨", 1.5)
    if oitrend > 0 and dn: return ("价跌仓增·空头加仓续跌", -1.5)
    if oitrend > 0:        return ("价平仓增·蓄势待方向", 0)
    if oitrend < 0 and up: return ("价涨仓减·空头回补/轧空(反弹非反转)", 0.5)
    if oitrend < 0 and dn: return ("价跌仓减·多头去杠杆", -0.5)
    if oitrend < 0:        return ("价平仓减·杠杆退出/观望", 0)
    return ("OI持平", 0)
def _t_global(b):
    if not b or b.get("ratio") is None: return ("—", 0)
    r = b["ratio"]
    if r > 2.0:  return ("Binance全站账户偏多拥挤→反向风险", -1)
    if r >= 1.3: return ("Binance全站账户偏多→反向风险", -0.3)
    if r >= 0.8: return ("Binance全站账户比中性", 0)
    return ("Binance全站账户偏空→反向线索", 1)
def _t_toppos(b):
    if not b or b.get("ratio") is None: return ("—", 0)
    r, tr = b["ratio"], b.get("trend", 0)
    if r > 1.2: return ("Binance头部持仓比净多" + ("·上升" if tr>0 else "·下降" if tr<0 else ""), 1.5 if tr>0 else 0.75)
    if r < 0.8: return ("Binance头部持仓比净空" + ("·下降" if tr<0 else "·上升" if tr>0 else ""), -1.5 if tr<0 else -0.75)
    return ("Binance头部持仓比中性", 0)
def _t_topacct(b):
    if not b or b.get("ratio") is None: return ("—", 0)
    r = b["ratio"]
    return ("Binance头部账户比净多" if r>1.1 else "Binance头部账户比净空" if r<0.9 else "Binance头部账户比中性", 0.5 if r>1.1 else -0.5 if r<0.9 else 0)
def _t_taker(tk):
    if not tk or tk.get("last") is None: return ("—", 0)
    l = tk["last"]
    if l > 1.2: return ("主动买盘吃单向上", 1)
    if l < 0.8: return ("主动卖盘砸盘", -1)
    return ("买卖均衡", 0)
def _t_struct(pr, l):
    if not l or pr is None or l.get("ema9") is None: return ("—", 0)
    e9, e21 = l["ema9"], l["ema21"]
    if pr > e9 > e21: return ("价在均线上方·多头排列", 1)
    if pr < e9 < e21: return ("价在均线下方·空头排列", -1)
    return ("均线缠绕·震荡", 0)
def _t_rsi(l):
    if not l or l.get("rsi14") is None: return ("—", 0)
    r = l["rsi14"]
    if r >= 70: return (f"RSI {r:.0f} 超买·追多谨慎", -0.5)
    if r >= 55: return (f"RSI {r:.0f} 偏强", 0.5)
    if r > 45:  return (f"RSI {r:.0f} 中性", 0)
    if r > 30:  return (f"RSI {r:.0f} 偏弱", -0.5)
    return (f"RSI {r:.0f} 超卖·反弹概率升", 1)
def _t_depth(d):
    if not d or d.get("ratio") is None: return ("—", 0)
    r = d["ratio"]
    if r > 1.3: return (f"买盘厚 {r:.2f}·近端支撑强", 0.7)
    if r < 0.77: return (f"卖盘厚 {r:.2f}·近端压力大", -0.7)
    return (f"盘口均衡 {r:.2f}", 0)

def signal_rows(price, levels, deriv, depth=None):
    pchgw = levels.get("price_chg_window_pct") if levels else None
    raw_funding = deriv.get("funding_rate")
    funding_interval = deriv.get("funding_interval_hours")
    fr8 = deriv.get("funding_rate_8h_equiv", deriv.get("funding_rate_8h"))
    if raw_funding is None:
        funding_display = "—"
    elif funding_interval:
        funding_display = f"{raw_funding*100:.4f}%/{funding_interval:g}h"
        if fr8 is not None and funding_interval != 8:
            funding_display += f" (8h等效{fr8*100:.4f}%)"
    else:
        funding_display = f"{raw_funding*100:.4f}%/周期未知"
    rows = [
        # A missing funding value is evidence of a failed/unavailable source,
        # not a zero funding rate.
        ("资金费率", funding_display, *_t_funding(fr8)),
        ("基差",     f"{_fmt(deriv.get('basis_pct'),3)}%", *_t_basis(deriv.get("basis_pct"))),
        ("持仓量OI", f"${_fmt(deriv.get('oi_usd'),0)} 窗口{_fmt(deriv.get('oi_chg_window_pct'))}%", *_t_oi(deriv.get("oi_trend"), pchgw)),
        ("Binance全站账户比", _fmt((deriv.get('global_ls') or {}).get('ratio')), *_t_global(deriv.get("global_ls"))),
        ("Binance头部持仓比", _fmt((deriv.get('top_position') or {}).get('ratio')), *_t_toppos(deriv.get("top_position"))),
        ("Binance头部账户比", _fmt((deriv.get('top_account') or {}).get('ratio')), *_t_topacct(deriv.get("top_account"))),
        ("Taker买卖比", _fmt((deriv.get('taker_buysell') or {}).get('last')), *_t_taker(deriv.get("taker_buysell"))),
        ("RSI14", _fmt((levels or {}).get('rsi14'), 0), *_t_rsi(levels)),
        ("结构均线", f"价{_fmt(price)}", *_t_struct(price, levels)),
    ]
    if depth is not None:
        rows.append(("盘口失衡", _fmt(depth.get("ratio")), *_t_depth(depth)))
    total = sum(r[3] for r in rows)
    if total >= 3:    bias = "偏多"
    elif total >= 1:  bias = "中性偏多"
    elif total > -1:  bias = "中性/震荡"
    elif total > -3:  bias = "中性偏空"
    else:             bias = "偏空"
    return rows, round(total, 2), bias

def _fmt(x, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)
def bias_emoji(s):
    if s >= 1:  return "偏多✅"
    if s > 0:   return "偏多"
    if s <= -1: return "偏空🔻"
    if s < 0:   return "偏空⚠️"
    return "中性➖"
