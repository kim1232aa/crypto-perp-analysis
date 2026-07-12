#!/usr/bin/env python3
"""Batch evidence scanner; it refuses to rank a partially populated score."""
import argparse

import perp_core as pc


VALID_BARS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")
OKX_BAR = {"1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H", "1d": "1D"}
MTF_LADDER = (("5m", "5m"), ("15m", "15m"), ("1H", "1H"), ("4H", "4H"))


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
        "资金费": deriv.get("funding_rate"),
        "资金费周期": deriv.get("funding_interval_hours"),
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
        okx_bar = OKX_BAR.get(args.bar, args.bar)
        candles = pc.okx_candles(symbol, okx_bar, 200, errors)
        levels = pc.build_levels(candles)
        deriv = pc.bn_derivs(symbol, args.bar, errors)
        depth = pc.okx_depth_imbalance(symbol, errors)
        okx_funding = pc.okx_funding(symbol, errors)
        bybit_funding = pc.bybit_funding(symbol, errors)

        mtf = []
        for label, tf_bar in MTF_LADDER:
            series = candles if tf_bar == okx_bar else pc.okx_candles(symbol, tf_bar, 200, errors)
            meta = (series or {}).get("meta", {})
            if (not series or len(series.get("closes", [])) < 30
                    or meta.get("continuity_ok") is not True or meta.get("freshness_ok") is not True):
                mtf.append((label, None, None, None, meta))
                continue
            closes = series["closes"]
            e9, e21, rsi_value = pc.ema(closes, 9), pc.ema(closes, 21), pc.rsi(closes)
            direction = 1 if closes[-1] > e9 > e21 else -1 if closes[-1] < e9 < e21 else 0
            mtf.append((label, direction, rsi_value, closes[-1], meta))

        quality = pc.assess_data_quality(
            price, levels, deriv, mtf, errors=errors, depth=depth,
            okx_funding=okx_funding, bybit_funding_rate=bybit_funding,
        )
        scoring_price = levels.get("last_close") if levels else None
        rows, raw_total, raw_bias = pc.signal_rows(scoring_price, levels, deriv, depth)
        status = quality["status"]
        score, bias = (raw_total, raw_bias) if status == "READY" else (None, "不排名")
        if quality["core_missing"]:
            reason = "核心缺失：" + "、".join(quality["core_missing"])
        elif quality["optional_missing"]:
            reason = "辅助缺失：" + "、".join(quality["optional_missing"])
        else:
            strongest = sorted((row for row in rows if row[3] != 0), key=lambda row: -abs(row[3]))[:2]
            reason = " / ".join(f"{row[0]}:{row[2]}" for row in strongest) or "信号平淡"
        results.append({
            "symbol": symbol, "price": (price or {}).get("last"), "change": (price or {}).get("chg24h_pct"),
            "rsi": (levels or {}).get("rsi14"), "status": status, "score": score, "bias": bias,
            "reason": reason, "quality": quality, "errors": errors,
        })

    ready = sorted((row for row in results if row["status"] == "READY"), key=lambda row: -row["score"])
    other = [row for row in results if row["status"] != "READY"]
    fmt = pc._fmt
    print(f"===== 多币扫描 · {args.bar} · 仅 READY 数据参与机械评分排名 =====\n")
    print("| 排名 | 币 | 数据状态 | 现价 | 24h% | RSI | 评分 | 偏向证据 | 说明 |")
    print("|---|---|---|---:|---:|---:|---:|---|---|")
    for index, row in enumerate(ready, 1):
        print(
            f"| {index} | {row['symbol']} | READY | {pc.format_price(row['price'])} | {fmt(row['change'])} | "
            f"{fmt(row['rsi'], 0)} | {fmt(row['score'])} | {row['bias']} | {row['reason']} |"
        )
    for row in other:
        print(
            f"| — | {row['symbol']} | {row['status']} | {pc.format_price(row.get('price'))} | {fmt(row.get('change'))} | "
            f"{fmt(row.get('rsi'), 0)} | — | 不排名 | {row['reason']} |"
        )

    if ready:
        print(f"\n最偏多证据：{ready[0]['symbol']}（评分 {fmt(ready[0]['score'])}）｜最偏空证据：{ready[-1]['symbol']}（评分 {fmt(ready[-1]['score'])}）")
        print(f"深入查看：python3 scripts/analyze.py {ready[0]['symbol']} {args.bar} --profile balanced")
    else:
        print("\n没有核心数据完整的标的；不输出方向排名。")
    error_count = sum(len(row.get("errors", [])) for row in results)
    print(f"\n⚠️ 扫描使用已收盘多周期K、核心衍生品与辅助快照，非回测/非交易建议；共记录 {error_count} 项源错误。")


if __name__ == "__main__":
    main()
