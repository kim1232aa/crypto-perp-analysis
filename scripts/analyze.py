#!/usr/bin/env python3
"""
crypto-perp-analysis :: detailed single-symbol report.
Fetches REAL data (OKX price/candles/depth, Binance derivatives, Bybit funding),
computes multi-timeframe resonance + RSI/ATR + orderbook imbalance + cross-exchange
funding, and prints a ready-to-paste 报告块. NEVER fabricates: failed sources -> errors[].

Usage:  python3 analyze.py [SYMBOL] [BAR]      e.g.  python3 analyze.py ETH 5m
Env:    HTTPS_PROXY/HTTP_PROXY respected.  No third-party deps.
"""
import sys, json
import perp_core as pc

HELP = """crypto-perp-analysis / analyze.py — 单币永续多空分析(实时真实数据)

用法: python3 analyze.py [SYMBOL] [BAR]
  SYMBOL  币种, 默认 ETH (BTC/SOL/BNB/XRP/DOGE... 任意 {SYM}-USDT 永续)
  BAR     周期, 默认 5m (5m/15m/30m/1h/2h/4h/6h/12h/1d)
环境: HTTPS_PROXY=http://<代理>:<端口> (交易所被墙时前缀)

输出: 一个【报告块】(必须原样完整输出,禁止改写成散文/删表), 含:
  快照 / 多周期共振(5m~4H) / 机械评分+基调 / 衍生品面板表 /
  跨所资金费(OKX·Binance·Bybit) / 关键位(ATR止损) / 情景剧本 / 总开关

数据源(公开,无需API key): OKX(价/K线/盘口) · Binance(OI/资金费/多空比/taker) · Bybit(资金费)

解读速查:
  OI×价: 涨+仓增=多头续涨 / 跌+仓增=空头续跌 / 涨+仓减=轧空反弹 / 平+仓增=蓄势
  散户多空比>1.3 拥挤多=反指偏空; 大户持仓比>1.2且回升=主力加多(顺势)
  taker>1.2 买盘强 / <0.8 卖盘强; 资金费>0.05%/8h 多头过热; RSI<30 超卖 / >70 超买
  止损=1.2×ATR; 总开关=swing_low_12(跌破转弱)

铁律: 只输出脚本给的数字,失败源写进errors不编造; 必带止损·非投资建议; 面板表强制原样输出。
姊妹脚本: scan.py(多币扫描排名) · alert.py(触发位监控,配 /loop)
"""
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help", "help"):
    print(HELP); sys.exit(0)

SYM = (sys.argv[1] if len(sys.argv) > 1 else "ETH").upper()
BAR = (sys.argv[2] if len(sys.argv) > 2 else "5m")
PERIOD = BAR if BAR in {"5m","15m","30m","1h","2h","4h","6h","12h","1d"} else "5m"
MTF_LADDER = ["5m", "15m", "1H", "4H"]

errors = []
price   = pc.okx_price(SYM, errors)
cd      = pc.okx_candles(SYM, BAR, 60, errors)
levels  = pc.build_levels(cd)
okx_fr  = pc.okx_funding(SYM, errors)
deriv   = pc.bn_derivs(SYM, PERIOD, errors)
depth   = pc.okx_depth_imbalance(SYM, errors)
byb_fr  = pc.bybit_funding(SYM, errors)

# ---- Multi-timeframe resonance ----
mtf = []
for tf in MTF_LADDER:
    c = pc.okx_candles(SYM, tf, 60, errors)
    if not c:
        mtf.append((tf, None, None, None)); continue
    cl = c["closes"]; e9 = pc.ema(cl[-30:], 9); e21 = pc.ema(cl[-30:], 21); r = pc.rsi(cl)
    d = 1 if (cl[-1] > e9 > e21) else -1 if (cl[-1] < e9 < e21) else 0
    mtf.append((tf, d, r, cl[-1]))
dirs = [d for _, d, _, _ in mtf if d is not None]
res_sum = sum(dirs)
if dirs and all(d > 0 for d in dirs):   resonance = "🟢多头共振(各周期同向向上·高信心)"
elif dirs and all(d < 0 for d in dirs): resonance = "🔴空头共振(各周期同向向下·高信心)"
elif res_sum > 0:  resonance = "偏多但未完全共振(存在分歧)"
elif res_sum < 0:  resonance = "偏空但未完全共振(存在分歧)"
else:              resonance = "多周期分歧·区间/转折(低信心,轻仓)"

pv = price["last"] if price else (levels["recent_closes"][-1] if levels else None)
rows, total, bias = pc.signal_rows(pv, levels, deriv, depth)

# ---------------- render ----------------
g = pc._fmt
def dtxt(d): return "↑多" if d == 1 else "↓空" if d == -1 else "→震荡" if d == 0 else "—"

print(f"===== {SYM}/USDT PERP · {BAR} · DATA REPORT =====")
if price:
    print(f"现价 {g(price['last'])} | 24h {g(price['chg24h_pct'])}% | 高 {g(price['high24h'])} 低 {g(price['low24h'])}")
if levels:
    print(f"RSI14 {g(levels['rsi14'],1)} | ATR14 {g(levels['atr14'])} | 背离 {levels['divergence'] or '无'}")

print("\n╔═══════ 报告块 · 必须原样完整输出 (禁止改写成散文 / 禁止删表删行) ═══════╗")
if price:
    print(f"**{SYM}/USDT 永续 · {BAR} · 实时快照**  现价 {g(price['last'])} | 24h {g(price['chg24h_pct'])}% | 高 {g(price['high24h'])} 低 {g(price['low24h'])}")

# 多周期共振
print(f"\n**多周期共振：{resonance}**")
print("| 周期 | 方向 | RSI |")
print("|---|---|---|")
for tf, d, r, c in mtf:
    print(f"| {tf} | {dtxt(d)} | {g(r,0)} |")

print(f"\n**机械评分 {total} → 基调:{bias}**（≥3偏多/1~3偏多/±1震荡/≤-1偏空；量化参考,结合共振与结构）\n")
print("| 指标 | 数值 | 解读 | 倾向 |")
print("|---|---|---|---|")
for name, val, desc, sc in rows:
    print(f"| {name} | {val} | {desc} | {pc.bias_emoji(sc)} |")
if levels and levels.get("divergence"):
    print(f"| RSI背离 | — | {levels['divergence']} | {'偏空🔻' if '偏空' in levels['divergence'] else '偏多✅'} |")

# 跨所资金费
def frp(x): return "—" if x is None else f"{x*100:.4f}%"
print(f"\n**跨所资金费(8h)**  OKX {frp(okx_fr)} ｜ Binance {frp(deriv.get('funding_rate_8h'))} ｜ Bybit {frp(byb_fr)}")
frs = [x for x in (okx_fr, deriv.get('funding_rate_8h'), byb_fr) if x is not None]
if len(frs) >= 2:
    sprd = (max(frs) - min(frs)) * 100
    print(f"  乖离 {sprd:.4f}%" + ("（三所一致·情绪统一）" if sprd < 0.01 else "（存在乖离·关注套利/分歧）"))

# 关键位 + ATR止损 + 情景剧本
if levels:
    sh30, sl30 = levels["swing_high_30"], levels["swing_low_30"]
    sh12, sl12 = levels["swing_high_12"], levels["swing_low_12"]
    atrv = levels.get("atr14") or 0
    if None not in (sh30, sl30, sh12, sl12) and pv:
        nd = 0 if pv > 100 else 2
        def q(x): return f"{x:.{nd}f}"
        u = atrv if atrv > 0 else max((sh30 - sl30) * 0.1, pv * 0.002)   # 止损单位=ATR
        rng = max(sh30 - sl30, 2 * u)                                     # 目标投影(≥2ATR)
        def rr(rw, rk): return f"1:{rw/rk:.1f}" if rk and rk > 0 else "—"
        newlow  = pv <= sl12 + 0.15 * u
        newhigh = pv >= sh12 - 0.15 * u
        regime = ("⚠️创窗口新低·下方无结构支撑,止损/目标以ATR测算" if newlow else
                  "⚠️创窗口新高·上方无结构压力,止损/目标以ATR测算" if newhigh else "")
        print(f"\n**关键位**  阻力 {q(sh30)}/{q(sh12)} ｜ 现价 {q(pv)} ｜ 支撑 {q(sl12)}(总开关)/{q(sl30)} ｜ ATR14 {q(atrv)}")
        if regime: print(regime)
        print("\n| 情景 | 触发 | 进场 | 止损(1.2ATR) | 目标 | R:R |")
        print("|---|---|---|---|---|---|")
        e = sl12;  st = sl12 - 1.2*u
        print(f"| 🟢低多回踩 | 回踩{q(sl12)}企稳 | {q(e)} | {q(st)} | {q(sh12)}→{q(sh30)} | {rr(sh30-e, e-st)} |")
        e = sh30;  st = sh30 - 1.2*u
        print(f"| 🟢突破多 | 站稳{q(sh30)} | {q(e)} | {q(st)} | {q(sh30+rng)} | {rr(rng, e-st)} |")
        e = sl12;  st = sl12 + 1.2*u
        print(f"| 🔴破位空 | 收破{q(sl12)} | {q(e)} | {q(st)} | {q(sl12-rng)} | {rr(rng, st-e)} |")
        e = sh30;  st = sh30 + 1.2*u
        print(f"| 🔴阻力空 | {q(sh30)}被拒 | {q(e)} | {q(st)} | {q(sl12)} | {rr(e-sl12, st-e)} |")
        print(f"\n**总开关 {q(sl12)}**：守住=偏多/低多；收破=转弱看 {q(sl12-rng)}。")

        # ---- 合并结论 & 建议 (确定性合成,强制输出) ----
        def drivers(pos_side, k=2):
            pool = [r for r in rows if (r[3] > 0) == pos_side and r[3] != 0]
            pool.sort(key=lambda r: -abs(r[3]))
            return pool[:k]
        bull, bear = drivers(True), drivers(False)
        gl, tp = deriv.get("global_ls"), deriv.get("top_position")
        pos = (pv - sl30) / rng if rng > 0 else 0.5
        near_res = pos > 0.8 or newhigh
        near_sup = pos < 0.2 or newlow
        zhuli = ("主力净多" if tp and tp["ratio"] > 1.1 else "主力净空" if tp and tp["ratio"] < 0.9 else "主力中性")
        print(f"\n**合并结论：{bias}**", end="")
        if bull: print(" ｜ 多方：" + "；".join(f"{n}({d})" for n, _, d, _ in bull), end="")
        if bear: print(" ｜ 空方/风险：" + "；".join(f"{n}({d})" for n, _, d, _ in bear), end="")
        print()
        if bias in ("偏多", "中性偏多"):
            rec = (f"🟢别追高·等回踩 {q(sl12)} 低多 或 站稳 {q(sh30)} 突破多" if near_res
                   else f"🟢首选低多：回踩 {q(sl12)} 进，止损 {q(sl12-1.2*u)}，目标 {q(sh12)}→{q(sh30)}")
        elif bias in ("偏空", "中性偏空"):
            rec = (f"🔴别追空·等反弹到 {q(sh12)}/{q(sh30)} 做空 或 收破 {q(sl12)} 破位空" if near_sup
                   else f"🔴首选反弹空/破位空：收破 {q(sl12)} 进空，止损 {q(sl12+1.2*u)}，目标 {q(sl12-rng)}")
        else:
            rec = f"➖区间震荡：{q(sl12)}~{q(sh30)} 高抛低吸，破位再跟"
        print(f"- **建议(主策略)**：{rec}")
        if gl and gl["ratio"] > 1.3:
            print(f"- **高胜率(踩踏)**：5m收破 {q(sl12)} → 散户拥挤多(比{g(gl['ratio'])})止损踩踏，快速下杀 {q(sl12-rng)}")
        elif gl and gl["ratio"] < 0.77:
            print(f"- **高胜率(逼空)**：站上 {q(sh30)} → 散户拥挤空(比{g(gl['ratio'])})被逼空，快速上冲 {q(sh30+rng)}")
        if gl and tp and tp["ratio"] < 0.9 and gl["ratio"] > 1.3:
            print(f"- **注意**：{zhuli}而散户拥挤多 → 主力散户背离,偏空,警惕多头踩踏")
        elif gl and tp and tp["ratio"] > 1.1 and gl["ratio"] > 1.3:
            print(f"- **注意**：{zhuli}但散户也拥挤多 → 跟主力做多,同时把散户止损位当踩踏触发,两手准备")
print("\n⚠️ 非投资建议·5M高噪音·务必带止损控杠杆。位与R:R为结构自动测算(R:R>1:6多因近端阻力太贴,实盘目标宜保守)。")
print("╚═══════ 报告块结束 · 以上须完整输出,尤其【面板表】与【合并结论/建议】不可省略 ═══════╝")

if errors:
    print("\n!!! 部分数据源失败(不要编造这些数字,如实告知) !!!")
    for e in errors: print("  -", e)

OUT = {"symbol": SYM, "bar": BAR, "price": price, "structure": levels, "okx_funding": okx_fr,
       "bybit_funding": byb_fr, "derivatives": deriv, "depth": depth,
       "mtf": [{"tf": t, "dir": d, "rsi": r, "close": c} for t, d, r, c in mtf],
       "resonance": resonance, "bias_score": total, "bias": bias, "errors": errors}
print("\n----- JSON -----")
print(json.dumps(OUT, ensure_ascii=False, separators=(",", ":")))
