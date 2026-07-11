#!/usr/bin/env python3
"""Batch evidence scanner; it refuses to rank a partially populated score."""
import argparse

import perp_core as pc


VALID_BARS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")
OKX_BAR = {"1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H", "1d": "1D"}


def bar_arg(value):
    bar = value.lower()
    if bar not in VALID_BARS:
        raise argparse.ArgumentTypeError(f"周期必须是: {', '.join(VALID_BARS)}")
    return bar


def parse_args():
    parser = argparse.ArgumentParser(
        description="多币结构化证据扫描；只有核心数据齐全的币才参与评分排名。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("symbols", nargs="?", default="BTC,ETH,SOL,BNB,XRP,DOGE", help="逗号分隔币种")
    parser.add_argument("bar", nargs="?", type=bar_arg, default="15m", help="周期")
    return parser.parse_args()


def missing_primary_derivatives(deriv):
    deriv = deriv or {}
    required = {
        "资金费": deriv.get("funding_rate_8h"),
        "OI": deriv.get("oi_usd"),
        "Binance全站账户比": (deriv.get("global_ls") or {}).get("ratio"),
        "Binance头部持仓比": (deriv.get("top_position") or {}).get("ratio"),
        "Taker": (deriv.get("taker_buysell") or {}).get("last"),
    }
    return [name for name, value in required.items() if value is None]


def main():
    args = parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    results = []

    for symbol in symbols:
        errors = []
        price = pc.okx_price(symbol, errors)
        candles = pc.okx_candles(symbol, OKX_BAR.get(args.bar, args.bar), 200, errors)
        levels = pc.build_levels(candles)
        deriv = pc.bn_derivs(symbol, args.bar, errors)
        if not price or not levels:
            results.append({"symbol": symbol, "status": "NO_TRADE", "reason": "缺少现价或30根已收盘K", "errors": errors})
            continue
        missing = missing_primary_derivatives(deriv)
        rows, total, bias = pc.signal_rows(price["last"], levels, deriv)
        strongest = sorted((row for row in rows if row[3] != 0), key=lambda row: -abs(row[3]))[:2]
        reason = " / ".join(f"{row[0]}:{row[2]}" for row in strongest) or "信号平淡"
        if missing:
            results.append({
                "symbol": symbol, "price": price["last"], "change": price["chg24h_pct"], "rsi": levels.get("rsi14"),
                "status": "CAUTION", "score": None, "bias": "不排名", "reason": "核心缺失：" + "、".join(missing), "errors": errors,
            })
            continue
        results.append({
            "symbol": symbol, "price": price["last"], "change": price["chg24h_pct"], "rsi": levels.get("rsi14"),
            "status": "READY", "score": total, "bias": bias, "reason": reason, "errors": errors,
        })

    ready = sorted((row for row in results if row["status"] == "READY"), key=lambda row: -row["score"])
    other = [row for row in results if row["status"] != "READY"]
    fmt = pc._fmt
    print(f"===== 多币扫描 · {args.bar} · 仅 READY 数据参与机械评分排名 =====\n")
    print("| 排名 | 币 | 数据状态 | 现价 | 24h% | RSI | 评分 | 偏向证据 | 说明 |")
    print("|---|---|---|---:|---:|---:|---:|---|---|")
    for index, row in enumerate(ready, 1):
        print(
            f"| {index} | {row['symbol']} | READY | {fmt(row['price'])} | {fmt(row['change'])} | "
            f"{fmt(row['rsi'], 0)} | {fmt(row['score'])} | {row['bias']} | {row['reason']} |"
        )
    for row in other:
        print(
            f"| — | {row['symbol']} | {row['status']} | {fmt(row.get('price'))} | {fmt(row.get('change'))} | "
            f"{fmt(row.get('rsi'), 0)} | — | 不排名 | {row['reason']} |"
        )

    if ready:
        print(f"\n最偏多证据：{ready[0]['symbol']}（评分 {fmt(ready[0]['score'])}）｜最偏空证据：{ready[-1]['symbol']}（评分 {fmt(ready[-1]['score'])}）")
        print(f"深入查看：python3 analyze.py {ready[0]['symbol']} {args.bar} --profile balanced")
    else:
        print("\n没有核心数据完整的标的；不输出方向排名。")
    error_count = sum(len(row.get("errors", [])) for row in results)
    print(f"\n⚠️ 扫描使用已收盘K和部分衍生品快照，非回测/非交易建议；共记录 {error_count} 项源错误。")


if __name__ == "__main__":
    main()
