---
name: crypto-perp-analysis
description: >-
  永续合约多空分析 / crypto perpetual futures long-short analysis. Fetches REAL
  live market data and produces a structured long/short readout with concrete
  entry/stop/target scenarios. Covers: OKX price+candles+orderbook, Binance
  derivatives (OI, funding, basis, long/short ratios, top-trader positioning,
  taker flow), Bybit funding; multi-timeframe resonance (5m/15m/1H/4H), RSI/ATR
  + divergence, orderbook imbalance, cross-exchange funding. Also batch-scans a
  watchlist (scan.py) and monitors trigger levels (alert.py + /loop). Use when
  the user asks for 行情/走势/多空分析, a scalping or swing read on ETH/BTC/SOL/etc
  perps, 5M/15M/1H 分析, coin screening, or mentions 资金费率/持仓量/OI/多空比/盘口/
  funding/open interest. Works for any {SYMBOL}-USDT perp (ETH, BTC, SOL, ...).
---

# Crypto Perp Long/Short Analysis

Turns a live market-data snapshot into an actionable long/short read. The hard
part other agents get wrong: **they hallucinate prices and indicator values.**
This skill forbids that — every number comes from the fetch script, and if a
source fails you say so instead of inventing it.

## Iron rules (do not break)

1. **NEVER write a number you did not get from `analyze.py`.** No made-up prices,
   RSI, support/resistance, funding, or ratios. If the script's `errors[]` is
   non-empty, state which source failed and analyze only what you have.
2. **FORCED OUTPUT — the whole 报告块 is mandatory, verbatim.** Everything the
   script prints between `╔═══ 报告块 ═══╗` and `╚═══ 报告块结束 ═══╝` MUST appear
   in your reply. In particular you **MUST NOT** compress the **面板表** into prose
   bullets or drop rows, and you **MUST** keep the **合并结论 / 建议(主策略) / 高胜率**
   lines. Keep the 面板表 as a markdown table (renders as a box). Add narration
   AROUND it — never instead of it.
3. **Always end with a risk line**: this is 技术分析 not 投资建议; 5M/15M are
   high-noise; every scenario carries a stop-loss + control-leverage note.
4. **Reply in the user's language** (this user: 中文 or 日本語 — never English).
5. Data is a **snapshot**; prices move. Say so, and offer to re-run/monitor.

## Step 1 — Fetch real data (mandatory first action)

```bash
python3 <skill_dir>/scripts/analyze.py <SYMBOL> <BAR>
# e.g.  python3 .../scripts/analyze.py ETH 5m
```
- Defaults: `ETH 5m`. `BAR` ∈ 5m,15m,30m,1h(=1H),2h,4h,6h,12h,1d.
- Stdlib-only, no deps. Respects `HTTPS_PROXY` env if OKX/Binance are geo/network
  blocked (try `HTTPS_PROXY=http://<your-proxy>:<port> python3 ...` as a fallback).
- **Multi-timeframe is now automatic** — one run computes 5m/15m/1H/4H resonance,
  so you do NOT need to run it twice.

The script prints three things:
1. `DATA REPORT` — human-readable raw numbers (incl. RSI/ATR/divergence).
2. **`报告块 (可直接粘贴给用户)`** — a **ready-to-paste markdown block**: 快照 +
   **多周期共振表** + 机械评分 + 衍生品面板表(含RSI/盘口失衡) + **跨所资金费(OKX/
   Binance/Bybit)** + 关键位(ATR止损) + 情景剧本(进场/止损/目标/RR) + 总开关 + 免责。
   **This is your primary deliverable.**
3. `JSON` — machine-readable, for programmatic use.

**A weaker agent's whole job = run the script, relay the 报告块 verbatim (never
change a number), then add 2–4 lines of 关键信号解读.** All indicators, signal
tags, bias score, resonance, and trade levels are computed IN the script (shared
lib `perp_core.py`), so output stays consistent no matter which agent runs it.

Sibling tools (same `scripts/` dir): **`scan.py`** batch-ranks a watchlist by
score; **`alert.py`** checks price vs trigger levels for monitoring. See
"Other tools" below.

## Step 2 — Interpret each metric (rubric)

**The script already applies this rubric** (tags + score are in the 报告块/JSON).
Use it to *understand and narrate* the tags — not to recompute or override them.
Thresholds:

**资金费率 funding_rate_8h** (background sentiment)
- `> +0.05%` 多头过热 → 追多有逼空反噬/回调风险 (偏空警戒)
- `+0.01% ~ +0.05%` 偏多但健康 · `-0.01% ~ +0.01%` 中性
- `< -0.01%` 空头付费；若价不跌=潜在轧空燃料 (反指偏多)
- (参考: 0.01%/8h ≈ 11% APR)

**基差 basis_pct** (mark vs index)
- `mark > index` 升水=永续被买高/投机偏多；过大(>+0.1%)=过热
- `mark < index` 贴水=现货主导/偏冷，健康或偏空 · `±0.03%` 内=中性

**OI (oi_trend) × 价格** — 最重要的组合，判断趋势"含金量":
- OI↑ + 价↑ = 多头加仓，续涨健康 (偏多)
- OI↑ + 价↓ = 空头加仓，续跌健康 (偏空)
- OI↓ + 价↑ = 空头回补/轧空 → 反弹非反转，警惕 (弱偏多，不追)
- OI↓ + 价↓ = 多头去杠杆离场 (弱偏空)
- OI↑ + 价平 = **蓄势**，方向选择将至=大波动前兆 (等触发)

**散户多空比 global_ls — 反向指标 (contrarian)**
- `>2.0` 极度拥挤多 → 强反指偏空 · `1.3~2.0` 偏多拥挤 → 弱反指警惕
- `0.8~1.3` 中性 · `<0.8` 拥挤空 → 反指偏多
- 拥挤方的止损=踩踏燃料：散户拥挤多时，跌破关键支撑会引发多杀多。

**大户持仓比 top_position — 顺向指标 (主力/smart money)**
- `>1.2` 且 trend↑ = 主力加多 (偏多✅) · `<0.8` 且 trend↓ = 主力加空 (偏空)
- **边际变化 (trend) 比绝对值更重要** — 主力在加还是在减？

**大户账户比 top_account** — 辅助确认方向，权重低于 top_position。

**Taker买卖比 taker_buysell** (主动成交/即时动能)
- `>1.2` 主动买盘吃单向上 (偏多) · `<0.8` 主动卖盘砸盘 (偏空)
- 单窗口噪音大，看 `last` + `series` 的连续性与 trend。用它验证"某个下影/上影是不是真有买盘/卖盘"。

**结构 structure** (来自 OKX K线)
- 现价 vs `ema9`/`ema21`: 上方偏多、下方偏空、缠绕=震荡
- `swing_low_12` = 反弹基准/**总开关**（跌破=转弱）
- `swing_high_30`/`swing_low_30` = 区间边界(阻力/支撑)
- 现价贴近 swing_high=顶着阻力(别追多)，贴近 swing_low=支撑(可低多)

**RSI14 + 背离 (rsi14 / divergence)**
- `≥70` 超买(续涨中但追多谨慎) · `55~70` 偏强 · `45~55` 中性 · `30~45` 偏弱 · `≤30` 超卖(反弹概率升)
- 背离最关键：**顶背离**(价新高RSI走弱)=偏空预警；**底背离**(价新低RSI走强)=偏多预警。背离常领先转折。

**ATR14** — 波动率，用于**止损幅度**。情景剧本止损=1.2×ATR(比固定构造位更适应波动)。ATR越大越要放宽止损/降杠杆。

**盘口失衡 depth (OKX ±0.5%)**
- `>1.3` 买盘厚=近端支撑强(偏多) · `<0.77` 卖盘厚=近端压力大(偏空) · 之间=均衡
- 反映即时挂单压力，适合验证"这个位置有没有人接/砸"。注意挂单可撤,只作短线佐证。

**多周期共振 resonance (5m/15m/1H/4H)**
- 各周期方向(价vs EMA9/21)全同向 = **共振=高信心**，顺势做；方向分歧 = 区间/转折,**低信心轻仓**。
- 用法：共振定"敢不敢重仓/顺不顺势"，单周期结构定"具体价位"。共振向上时低多更稳，共振分歧时只做区间。

**跨所资金费 (OKX / Binance / Bybit)**
- 三所费率一致=情绪统一；明显乖离=分歧或套利机会(某所多头更热/更冷)。
- 某所深度负费率而价不跌=该所潜在轧空燃料。

## Step 3 — Synthesize the bias

Weight (high→low): `多周期共振(信心)` ≈ `OI×价 组合` ≈ `top_position` ≈ `taker`
> `structure/RSI背离(定位与转折)` > `盘口失衡(即时)` > `global_ls(反指)` >
`funding/basis/跨所(背景)`. 共振定信心，结构定价位，衍生品定方向。

- 多数信号偏多 + 现价不在阻力 → **偏多，可顺势/低多**
- 偏多 + 现价顶着阻力 → **偏多但别追，等回踩低多 或 突破确认**
- 信号打架 / OI↑价平 → **中性震荡，区间高抛低吸，等触发位破位再跟**
- 散户极度拥挤某一方 → 提示"踩踏方向"，把反向破位列为高胜率交易

## Step 4 — Output (in user's language)

1. **Relay the ENTIRE 报告块 verbatim** — 快照 + 多周期共振 + 面板表 + 跨所资金费 +
   关键位 + 情景剧本 + 总开关 + **合并结论 / 建议 / 高胜率**. Keep the 面板表 as a
   markdown table. Do NOT alter a number, drop a row, or turn the table into prose.
2. **Add 关键信号解读** — 2~4 lines ON TOP of (not replacing) the block: the *story*
   joining tags. e.g. "主力加多 + taker买盘 → 下影是买盘防守，不是空头没力"。
3. **The script already picks the play** (建议/主策略/高胜率是脚本生成的); reinforce
   it with reasoning if useful, but never contradict, omit, or overwrite it.
4. **Caveat + offer** — 非投资建议已在报告块内；再提议 5 分钟自动监控 (alert.py)。

Note on the 情景剧本 R:R: stops = 1.2×ATR, targets = structure/ATR projection.
若 R:R 高得离谱(如 >1:6)或四行RR接近相同，通常是价格贴近窗口高/低点(结构压缩,脚本会
标⚠️创新高/新低)或近端阻力太贴——narrate it as "结构测算,实盘目标宜保守",别当真实胜率照搬。

### Reference: the shape of a good final answer

```
## 实时快照 (OKX/Binance 永续 · 快照)
现价 1794 | 24h +0.6% | 高1808 低1727 | ...

## 衍生品面板
资金费 +0.008%/8h → 不过热 → 中性偏多
OI $4.16B 近1h +0.28% 价平 → 蓄势加仓
散户多空比 1.60 → 偏多拥挤 → 反指偏空⚠️
大户持仓比 1.40↑ → 主力加多 → 偏多✅
Taker 1.58→1.60 → 买盘接管 → 偏多✅

## 关键信号
1. 主力低多、taker买盘防守了1790下影 → 不是空头没力
2. 散户60%拥挤多，止损全在1785下 → 破位=踩踏燃料
3. 资金费低=无逼空风险，向上有空间

## 结论：短线偏多，主力低多，散户反向隐患
- ✅ 首选 低多：回踩1787-1790进，止损1785下，目标1794→1799→1804 (R:R≈1:2.5)
- ✅ 突破多：站稳1796追，目标1800→1804
- ⚠️ 最高胜率空：5m收破1785=引爆散户踩踏，下看1780→1775
- 🔻 阻力空(快进出)：1799-1800被拒，止损1802上

▎总开关1785：守住跟主力低多；跌破反手做空看1775。现价顶阻力别追。

数据为实时快照，非投资建议，务必带止损控杠杆。要做5分钟自动监控盯1785/1796吗？
```

## Other tools

**`scan.py` — 多币批量扫描** (screen a watchlist, rank by score):
```bash
python3 <skill_dir>/scripts/scan.py [SYM1,SYM2,...] [BAR]
# python3 scan.py BTC,ETH,SOL,BNB,XRP,DOGE 15m   (defaults: that list, 15m)
```
Prints a ranked markdown table (偏多在上) with 现价/24h/RSI/评分/基调/主导信号, and
names the most-bullish & most-bearish. Use to find setups, then drill in with
`analyze.py <SYM> <BAR>`. Lightweight (price+derivatives only, no 盘口/多周期) — say so.

**`alert.py` — 触发位监控** (one-shot price-vs-trigger, for /loop):
```bash
python3 <skill_dir>/scripts/alert.py SYMBOL SUPPORT RESISTANCE
# python3 alert.py ETH 1785 1796
```
Prints one line: 🔴破位 (跌破支撑) / 🟢突破 (站上阻力) / ⚪区间内 (with 位置%).

**5-minute monitor** — wire the `/loop` skill to re-run `alert.py` every 5m with
the 总开关支撑 / 突破阻力 from a prior `analyze.py`, and surface when the line
starts 🔴/🟢. Only propose this; **don't start a loop unprompted.** Example:
`/loop 5m python3 <skill_dir>/scripts/alert.py ETH 1785 1796`.

## Files
- `scripts/perp_core.py` — shared lib (fetch + indicators + tags). Don't run directly.
- `scripts/analyze.py` — detailed single-symbol report (primary tool).
- `scripts/scan.py` — batch watchlist scanner.
- `scripts/alert.py` — trigger-level monitor for /loop.
