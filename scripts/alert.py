#!/usr/bin/env python3
"""
alert.py :: one-shot price-vs-trigger check for monitoring (wire into /loop).

Usage:
    python3 alert.py SYMBOL SUPPORT RESISTANCE
    python3 alert.py ETH 1785 1796
Prints a single concise status line. Designed to be re-run every 5m by /loop:
the loop should surface the line and highlight when status starts with 🔴/🟢.
"""
import sys
import perp_core as pc

if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help", "help"):
    print("""alert.py — 触发位监控,一发式检查(配 /loop 做5分钟自动盯盘)

用法: python3 alert.py SYMBOL SUPPORT RESISTANCE
  例: python3 alert.py ETH 1785 1796
输出一行: 🔴破位(跌破支撑) / 🟢突破(站上阻力) / ⚪区间内(含位置%)
配合 /loop: /loop 5m python3 <path>/alert.py ETH 1785 1796
SUPPORT/RESISTANCE 通常取自 analyze.py 的 总开关支撑 / 突破阻力。""")
    sys.exit(0)
if len(sys.argv) < 4:
    print("用法: python3 alert.py SYMBOL SUPPORT RESISTANCE  (-h 看详情)"); sys.exit(2)
SYM = sys.argv[1].upper()
support = float(sys.argv[2]); resistance = float(sys.argv[3])

errs = []
price = pc.okx_price(SYM, errs)
if not price:
    print(f"⚠️ {SYM} 价格获取失败(不要编造): {'; '.join(errs)}"); sys.exit(1)
last = price["last"]
if last <= support:
    status = f"🔴破位 {SYM} {last} 跌破支撑{support} → 转弱/破位空信号"
elif last >= resistance:
    status = f"🟢突破 {SYM} {last} 站上阻力{resistance} → 突破多信号"
else:
    pos = (last - support) / (resistance - support) * 100 if resistance > support else 0
    status = f"⚪区间内 {SYM} {last}（支撑{support}~阻力{resistance}, 位置{pos:.0f}%）24h {price['chg24h_pct']:.2f}%"
print(status)
