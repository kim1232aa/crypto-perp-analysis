#!/usr/bin/env python3
"""
perp_core :: shared data-fetch + indicator + signal-tagging library.
Used by analyze.py (detailed single-symbol), scan.py (batch), alert.py (monitor).
Stdlib only. NEVER fabricates: every fetch returns (data, error); callers surface errors.
"""
import json, urllib.request

def get(url):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
              "User-Agent": "Mozilla/5.0 (perp-analysis)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def num(x):
    try: return float(x)
    except: return None
def pct(a, b): return None if not b else (a - b) / b * 100.0

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
def okx_price(sym, errors):
    d, e = get(f"https://www.okx.com/api/v5/market/ticker?instId={sym}-USDT-SWAP")
    if e: errors.append(f"OKX ticker: {e}"); return None
    if not d.get("data"): return None
    x = d["data"][0]
    return {"last": num(x["last"]), "open24h": num(x["open24h"]), "high24h": num(x["high24h"]),
            "low24h": num(x["low24h"]), "chg24h_pct": pct(num(x["last"]), num(x["open24h"])),
            "bid": num(x.get("bidPx")), "ask": num(x.get("askPx"))}
def okx_candles(sym, bar, limit, errors):
    d, e = get(f"https://www.okx.com/api/v5/market/candles?instId={sym}-USDT-SWAP&bar={bar}&limit={limit}")
    if e: errors.append(f"OKX candles {bar}: {e}"); return None
    if not d.get("data"): return None
    ch = list(reversed(d["data"]))  # chronological
    return {"highs": [num(r[2]) for r in ch], "lows": [num(r[3]) for r in ch],
            "closes": [num(r[4]) for r in ch]}
def okx_funding(sym, errors):
    d, e = get(f"https://www.okx.com/api/v5/public/funding-rate?instId={sym}-USDT-SWAP")
    if e: errors.append(f"OKX funding: {e}"); return None
    return num(d["data"][0]["fundingRate"]) if d.get("data") else None
def okx_depth_imbalance(sym, errors, band=0.005):
    d, e = get(f"https://www.okx.com/api/v5/market/books?instId={sym}-USDT-SWAP&sz=50")
    if e: errors.append(f"OKX depth: {e}"); return None
    if not d.get("data"): return None
    b = d["data"][0].get("bids", []); a = d["data"][0].get("asks", [])
    if not b or not a: return None
    mid = (num(b[0][0]) + num(a[0][0])) / 2; lo, hi = mid*(1-band), mid*(1+band)
    bidv = sum(num(x[1]) for x in b if num(x[0]) >= lo)
    askv = sum(num(x[1]) for x in a if num(x[0]) <= hi)
    return {"ratio": bidv/askv if askv else None, "bidv": bidv, "askv": askv, "band": band}

def build_levels(cd):
    """cd = okx_candles dict -> structure + indicators."""
    if not cd: return None
    c, h, l = cd["closes"], cd["highs"], cd["lows"]; n = len(c)
    return {"candles": n,
            "swing_high_30": max(h[-30:]), "swing_low_30": min(l[-30:]),
            "swing_high_12": max(h[-12:]), "swing_low_12": min(l[-12:]),
            "ema9": round(ema(c[-30:], 9), 4), "ema21": round(ema(c[-30:], 21), 4),
            "rsi14": rsi(c), "atr14": atr(h, l, c),
            "divergence": divergence(c),
            "price_chg_window_pct": pct(c[-1], c[-13]) if n >= 13 else None,
            "recent_closes": [round(x, 4) for x in c[-12:]]}

# ---------------- Binance derivatives ----------------
def bn_derivs(sym, period, errors):
    B = "https://fapi.binance.com"; s = f"{sym}USDT"; out = {}
    pi, e = get(f"{B}/fapi/v1/premiumIndex?symbol={s}")
    if e: errors.append(f"BN premiumIndex: {e}")
    elif pi:
        mark, idx, fr = num(pi.get("markPrice")), num(pi.get("indexPrice")), num(pi.get("lastFundingRate"))
        out.update({"funding_rate_8h": fr, "funding_apr_pct": None if fr is None else fr*3*365*100,
                    "mark": mark, "index": idx, "basis_pct": pct(mark, idx) if (mark and idx) else None})
    oi, e = get(f"{B}/futures/data/openInterestHist?symbol={s}&period={period}&limit=12")
    if e: errors.append(f"BN OI: {e}")
    elif isinstance(oi, list) and oi:
        ser = [num(x["sumOpenInterest"]) for x in oi]
        out.update({"oi_now": ser[-1], "oi_usd": num(oi[-1]["sumOpenInterestValue"]),
                    "oi_chg_window_pct": pct(ser[-1], ser[0]), "oi_trend": wtrend(ser)})
    def lsb(path, tag):
        dd, ee = get(f"{B}/futures/data/{path}?symbol={s}&period={period}&limit=6")
        if ee: errors.append(f"BN {tag}: {ee}"); return None
        if not (isinstance(dd, list) and dd): return None
        ser = [num(x["longShortRatio"]) for x in dd]; last = dd[-1]
        return {"ratio": ser[-1], "long_pct": num(last.get("longAccount")),
                "short_pct": num(last.get("shortAccount")), "trend": wtrend(ser)}
    out["global_ls"]    = lsb("globalLongShortAccountRatio", "global L/S")
    out["top_account"]  = lsb("topLongShortAccountRatio", "top acct")
    out["top_position"] = lsb("topLongShortPositionRatio", "top pos")
    tk, e = get(f"{B}/futures/data/takerlongshortRatio?symbol={s}&period={period}&limit=6")
    if e: errors.append(f"BN taker: {e}")
    elif isinstance(tk, list) and tk:
        ser = [num(x["buySellRatio"]) for x in tk]
        out["taker_buysell"] = {"last": ser[-1], "series": [round(x,3) for x in ser], "trend": wtrend(ser)}
    t24, e = get(f"{B}/fapi/v1/ticker/24hr?symbol={s}")
    if not e and t24:
        out["binance_24h"] = {"last": num(t24.get("lastPrice")), "chg_pct": num(t24.get("priceChangePercent")),
                              "high": num(t24.get("highPrice")), "low": num(t24.get("lowPrice")),
                              "quote_vol_usd": num(t24.get("quoteVolume"))}
    return out

def bybit_funding(sym, errors):
    d, e = get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}USDT")
    if e: errors.append(f"Bybit funding: {e}"); return None
    try: return num(d["result"]["list"][0]["fundingRate"])
    except: return None

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
    return ("OI持平", 0)
def _t_global(b):
    if not b: return ("—", 0)
    r = b["ratio"]
    if r > 2.0:  return ("散户极度拥挤多→强反指偏空", -1)
    if r >= 1.3: return ("散户偏多拥挤→弱反指警惕", -0.3)
    if r >= 0.8: return ("散户中性", 0)
    return ("散户拥挤空→反指偏多", 1)
def _t_toppos(b):
    if not b: return ("—", 0)
    r, tr = b["ratio"], b["trend"]
    if r > 1.2: return ("主力净多" + ("·加多" if tr>0 else "·减多" if tr<0 else ""), 1.5 if tr>0 else 0.75)
    if r < 0.8: return ("主力净空" + ("·加空" if tr<0 else "·减空" if tr>0 else ""), -1.5 if tr<0 else -0.75)
    return ("主力中性", 0)
def _t_topacct(b):
    if not b: return ("—", 0)
    r = b["ratio"]
    return ("大户净多" if r>1.1 else "大户净空" if r<0.9 else "大户中性", 0.5 if r>1.1 else -0.5 if r<0.9 else 0)
def _t_taker(tk):
    if not tk: return ("—", 0)
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
    fr8 = deriv.get("funding_rate_8h")
    rows = [
        ("资金费率", f"{(fr8 or 0)*100:.4f}%/8h", *_t_funding(fr8)),
        ("基差",     f"{_fmt(deriv.get('basis_pct'),3)}%", *_t_basis(deriv.get("basis_pct"))),
        ("持仓量OI", f"${_fmt(deriv.get('oi_usd'),0)} 窗口{_fmt(deriv.get('oi_chg_window_pct'))}%", *_t_oi(deriv.get("oi_trend"), pchgw)),
        ("散户多空比", _fmt((deriv.get('global_ls') or {}).get('ratio')), *_t_global(deriv.get("global_ls"))),
        ("大户持仓比", _fmt((deriv.get('top_position') or {}).get('ratio')), *_t_toppos(deriv.get("top_position"))),
        ("大户账户比", _fmt((deriv.get('top_account') or {}).get('ratio')), *_t_topacct(deriv.get("top_account"))),
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
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))
def bias_emoji(s):
    if s >= 1:  return "偏多✅"
    if s > 0:   return "偏多"
    if s <= -1: return "偏空🔻"
    if s < 0:   return "偏空⚠️"
    return "中性➖"
