#!/usr/bin/env python3
"""One-shot level monitor with explicit live-warning vs closed-candle semantics."""
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
        description="触发位监控：默认只给实时预警；--confirm-closed 才给已收盘确认。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("symbol", help="币种，例如 ETH")
    parser.add_argument("support", type=float, help="支撑/下破观察位")
    parser.add_argument("resistance", type=float, help="阻力/上破观察位")
    parser.add_argument(
        "--confirm-closed", type=bar_arg, metavar="BAR",
        help="以指定周期的已收盘K确认；未指定时绝不输出交易触发",
    )
    parser.add_argument(
        "--profile", choices=tuple(pc.PROFILES), default="balanced",
        help="确认所需已收盘K根数；仅在 --confirm-closed 下使用",
    )
    args = parser.parse_args()
    if args.support >= args.resistance:
        parser.error("support 必须小于 resistance")
    return args


def main():
    args = parse_args()
    sym = args.symbol.upper()
    profile = pc.profile_config(args.profile)
    errors = []
    price = pc.okx_price(sym, errors)
    if not price or price.get("last") is None:
        detail = "; ".join(errors) or "空响应"
        print(f"⚠️ {sym} 价格获取失败（不生成信号）：{detail}")
        return 1

    last = price["last"]
    live_state = "breakdown" if last <= args.support else "breakout" if last >= args.resistance else None

    # Backwards-compatible positional invocation is intentionally a warning
    # only. A live price can cross a level and reverse before a bar closes.
    if not args.confirm_closed:
        if live_state == "breakdown":
            print(f"⚠️ 下破预警 {sym} {last} ≤ 支撑{args.support}：实时触价，未做已收盘确认；非交易触发。")
        elif live_state == "breakout":
            print(f"⚠️ 上破预警 {sym} {last} ≥ 阻力{args.resistance}：实时触价，未做已收盘确认；非交易触发。")
        else:
            position = (last - args.support) / (args.resistance - args.support) * 100
            print(f"⚪区间内 {sym} {last}（支撑{args.support}~阻力{args.resistance}, 位置{position:.0f}%）24h {price['chg24h_pct']:.2f}%")
        print("提示：如需已收盘确认，使用 --confirm-closed 5m（可配 --profile）。")
        return 0

    bar = args.confirm_closed
    candles = pc.okx_candles(sym, OKX_BAR.get(bar, bar), max(5, profile["confirmed_closes"] + 2), errors)
    closes = candles["closes"] if candles else []
    confirmed = pc.level_confirmation(closes, args.support, args.resistance, profile["confirmed_closes"])
    close_text = "—" if not closes else f"{closes[-1]}（ts {candles['timestamps'][-1]}）"

    if confirmed == "breakdown":
        print(
            f"🔴 已收盘确认破位 {sym}：最近 {profile['confirmed_closes']} 根 {bar} K 收在支撑{args.support}下方 "
            f"（最后收盘 {close_text}）。这是条件确认，不保证成交或后续走势。"
        )
    elif confirmed == "breakout":
        print(
            f"🟢 已收盘确认突破 {sym}：最近 {profile['confirmed_closes']} 根 {bar} K 收在阻力{args.resistance}上方 "
            f"（最后收盘 {close_text}）。这是条件确认，不保证成交或后续走势。"
        )
    elif live_state == "breakdown":
        print(
            f"⚠️ 下破预警 {sym} {last} ≤ 支撑{args.support}，但最近已收盘 {bar} K 未满足 "
            f"{profile['confirmed_closes']} 根确认（最后收盘 {close_text}）。"
        )
    elif live_state == "breakout":
        print(
            f"⚠️ 上破预警 {sym} {last} ≥ 阻力{args.resistance}，但最近已收盘 {bar} K 未满足 "
            f"{profile['confirmed_closes']} 根确认（最后收盘 {close_text}）。"
        )
    else:
        position = (last - args.support) / (args.resistance - args.support) * 100
        print(
            f"⚪区间内 {sym} {last}（支撑{args.support}~阻力{args.resistance}, 位置{position:.0f}%）；"
            f"最后已收盘 {bar} K {close_text}，未确认突破/破位。"
        )

    if errors:
        print("数据提示：" + "; ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
