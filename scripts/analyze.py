#!/usr/bin/env python3
"""Detailed, evidence-first crypto perpetual snapshot.

The script deliberately separates live observations, structural candidates and
execution assumptions.  It is not a backtester and it does not select a single
mandatory trade for an agent or a user.
"""
import argparse
import json

import perp_core as pc


VALID_BARS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")
OKX_BAR = {"1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H", "1d": "1D"}
MTF_LADDER = (("5m", "5m"), ("15m", "15m"), ("1H", "1H"), ("4H", "4H"))


def bar_arg(value):
    bar = value.lower()
    if bar not in VALID_BARS:
        raise argparse.ArgumentTypeError(f"周期必须是: {', '.join(VALID_BARS)}")
    return bar


def non_negative(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是数字") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("不能为负数")
    return number


def positive(value):
    number = non_negative(value)
    if number == 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


def parse_args():
    parser = argparse.ArgumentParser(
        description="永续合约结构化证据快照（非回测、非交易指令）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("symbol", nargs="?", default="ETH", help="币种，例如 ETH/BTC/SOL")
    parser.add_argument("bar", nargs="?", type=bar_arg, default="5m", help="主分析周期")
    parser.add_argument(
        "--profile", choices=tuple(pc.PROFILES), default="balanced",
        help="候选情景的确认/风险提示档位；不改变数据和指标",
    )
    parser.add_argument(
        "--fee-bps", type=non_negative, default=4.0,
        help="单边手续费估算（bp；非交易所报价，请按实际账户覆盖）",
    )
    parser.add_argument(
        "--slippage-bps", type=non_negative, default=2.0,
        help="单边滑点估算（bp；非回测结果）",
    )
    parser.add_argument(
        "--risk-pct", type=positive,
        help="可选：用户设定的单笔账户风险上限（%%），仅用于仓位公式；未提供时不假设风险偏好",
    )
    parser.add_argument(
        "--account-equity", type=positive,
        help="可选账户权益（USDT），给出近似标的数量/名义价值；不含合约乘数",
    )
    return parser.parse_args()


def mtf_resonance(mtf):
    """Do not call a partial ladder a full multi-timeframe resonance."""
    dirs = [direction for _, direction, _, _ in mtf if direction is not None]
    if len(dirs) != len(MTF_LADDER):
        return "数据不完整·不声明多周期共振"
    if all(direction > 0 for direction in dirs):
        return "🟢多头共振（四个已收盘周期同向）"
    if all(direction < 0 for direction in dirs):
        return "🔴空头共振（四个已收盘周期同向）"
    total = sum(dirs)
    if total > 0:
        return "偏多但存在周期分歧"
    if total < 0:
        return "偏空但存在周期分歧"
    return "多周期分歧·区间/转折"


def fmt(value, digits=2):
    return pc._fmt(value, digits)


def direction_text(direction):
    return "↑多" if direction == 1 else "↓空" if direction == -1 else "→震荡" if direction == 0 else "—"


def rr_value(reward, risk):
    return reward / risk if risk and risk > 0 else None


def rr_text(value):
    return "—" if value is None else f"1:{value:.1f}"


def candidate(name, trigger, entry, stop, targets, rr):
    return {
        "name": name,
        "trigger": trigger,
        "entry": entry,
        "stop": stop,
        "targets": targets,
        "rr_structural": rr,
        "risk_distance_pct": abs(entry - stop) / entry * 100 if entry else None,
    }


def execution_summary(args, profile, funding_rate, candidates):
    """Return explicit, non-backtested execution assumptions and sizing maths."""
    one_way_bps = args.fee_bps + args.slippage_bps
    round_trip_bps = one_way_bps * 2
    effective_risk_pct = args.risk_pct * profile["risk_fraction"] if args.risk_pct is not None else None
    out = {
        "fee_bps_each_way": args.fee_bps,
        "slippage_bps_each_way": args.slippage_bps,
        "estimated_round_trip_bps": round_trip_bps,
        "funding_rate_8h": funding_rate,
        "risk_pct_input": args.risk_pct,
        "profile_risk_fraction": profile["risk_fraction"],
        "effective_risk_pct": effective_risk_pct,
        "account_equity": args.account_equity,
        "sizing": [],
        "disclaimer": "成本/滑点/资金费为输入估算，非实盘回测或成交保证。",
    }
    if args.account_equity is None or effective_risk_pct is None:
        return out

    risk_budget = args.account_equity * effective_risk_pct / 100
    for item in candidates:
        entry, stop = item["entry"], item["stop"]
        # A simple linear-perp approximation: stop distance plus the estimated
        # two-way cost.  Contract multiplier, fills and liquidation are outside
        # this formula and are stated in the rendered report.
        per_unit_loss = abs(entry - stop) + entry * round_trip_bps / 10_000
        quantity = risk_budget / per_unit_loss if per_unit_loss > 0 else None
        out["sizing"].append({
            "name": item["name"],
            "risk_budget": risk_budget,
            "per_unit_loss_estimate": per_unit_loss,
            "quantity_estimate": quantity,
            "notional_estimate": quantity * entry if quantity is not None else None,
        })
    return out


def render_execution_summary(execution):
    print("\n**执行/风险估算（输入假设，非回测）**")
    print(
        f"单边费用 {execution['fee_bps_each_way']:.2f}bp ｜ "
        f"单边滑点 {execution['slippage_bps_each_way']:.2f}bp ｜ "
        f"往返成本估算 {execution['estimated_round_trip_bps']:.2f}bp"
    )
    funding = execution["funding_rate_8h"]
    funding_text = "—（数据缺失，不计入R:R）" if funding is None else f"{funding * 100:.4f}%/8h（持仓跨结算时另计）"
    print(f"Binance 最新资金费 {funding_text}")
    if execution["risk_pct_input"] is None:
        print(f"用户风险上限：未提供（档位系数 {execution['profile_risk_fraction']:.2f} 不单独构成风险偏好）。")
    else:
        print(
            f"用户风险上限 {execution['risk_pct_input']:.3f}% × 档位系数 "
            f"{execution['profile_risk_fraction']:.2f} = 估算有效风险上限 "
            f"{execution['effective_risk_pct']:.3f}%"
        )
    if execution["account_equity"] is None or execution["effective_risk_pct"] is None:
        print("仓位公式：账户权益 × 有效风险上限 ÷（进场至止损距离 + 进场价×往返成本）。同时提供 --risk-pct 和 --account-equity 才生成近似值。")
    else:
        print("| 候选情景 | 风险预算(USDT) | 每标的单位估算亏损 | 近似标的数量 | 近似名义价值 |")
        print("|---|---:|---:|---:|---:|")
        for row in execution["sizing"]:
            print(
                f"| {row['name']} | {row['risk_budget']:.2f} | {row['per_unit_loss_estimate']:.4f} | "
                f"{row['quantity_estimate']:.6f} | {row['notional_estimate']:.2f} |"
            )
        print("近似值未含合约乘数、维持保证金、资金费、限价未成交或清算风险。")
    print("R:R 仍是结构距离，不扣除资金费、实际手续费或实际滑点。")


def main():
    args = parse_args()
    sym = args.symbol.upper()
    bar = args.bar
    okx_bar = OKX_BAR.get(bar, bar)
    profile = pc.profile_config(args.profile)
    errors = []

    # 200 returned bars leave ample closed history after removing a current bar.
    price = pc.okx_price(sym, errors)
    candles = pc.okx_candles(sym, okx_bar, 200, errors)
    levels = pc.build_levels(candles)
    okx_funding = pc.okx_funding(sym, errors)
    deriv = pc.bn_derivs(sym, bar, errors)
    depth = pc.okx_depth_imbalance(sym, errors)
    bybit_funding = pc.bybit_funding(sym, errors)

    mtf = []
    for label, tf_bar in MTF_LADDER:
        series = candles if tf_bar == okx_bar else pc.okx_candles(sym, tf_bar, 200, errors)
        if not series or len(series["closes"]) < 30:
            mtf.append((label, None, None, None))
            continue
        closes = series["closes"]
        e9, e21, rsi_value = pc.ema(closes, 9), pc.ema(closes, 21), pc.rsi(closes)
        direction = 1 if closes[-1] > e9 > e21 else -1 if closes[-1] < e9 < e21 else 0
        mtf.append((label, direction, rsi_value, closes[-1]))

    pv = price["last"] if price else (levels["recent_closes"][-1] if levels else None)
    rows, total, bias = pc.signal_rows(pv, levels, deriv, depth)
    quality = pc.assess_data_quality(
        price, levels, deriv, mtf, errors=errors, depth=depth,
        okx_funding=okx_funding, bybit_funding_rate=bybit_funding,
    )
    resonance = mtf_resonance(mtf)

    print(f"===== {sym}/USDT PERP · {bar} · STRUCTURED EVIDENCE =====")
    if price:
        print(f"现价 {fmt(price['last'])} | 24h {fmt(price['chg24h_pct'])}% | 高 {fmt(price['high24h'])} 低 {fmt(price['low24h'])}")
    if levels:
        meta = levels.get("candle_meta", {})
        print(
            f"结构仅用已收盘K：{levels['candles']}根 | 最后一根时间戳 {levels['last_candle_ts']} | "
            f"本次忽略未收盘K {meta.get('dropped_unconfirmed', 0)} 根"
        )
        print(f"RSI14 {fmt(levels['rsi14'], 1)} | ATR14 {fmt(levels['atr14'])} | 背离 {levels['divergence'] or '无'}")

    print("\n**数据质量**")
    print(f"状态：**{quality['status']}** ｜ 已收盘结构K {quality['confirmed_structure_candles']} 根 ｜ API错误 {quality['error_count']} 项")
    if quality["core_missing"]:
        print("核心缺失：" + "、".join(quality["core_missing"]))
    if quality["optional_missing"]:
        print("辅助缺失：" + "、".join(quality["optional_missing"]))
    if quality["status"] == "NO_TRADE":
        print("操作状态：**NO_TRADE**。下方仅保留可用的结构化证据/候选价位，不生成交易指令。")
    elif quality["status"] == "CAUTION":
        print("操作状态：**CAUTION**。核心证据齐全，但应明确考虑缺失的辅助来源。")
    else:
        print("操作状态：**READY（数据完整性）**。READY 不代表策略经回测验证或应当交易。")

    print(f"\n**多周期证据：{resonance}**")
    print("| 周期 | 方向 | RSI | 最后已收盘价 |")
    print("|---|---|---:|---:|")
    for tf, direction, rsi_value, close in mtf:
        print(f"| {tf} | {direction_text(direction)} | {fmt(rsi_value, 0)} | {fmt(close)} |")

    print(f"\n**机械评分 {total} → 偏向证据:{bias}**（手工规则，非预测概率或交易命令）\n")
    print("| 指标 | 数值 | 解读 | 倾向 |")
    print("|---|---|---|---|")
    for name, value, description, score in rows:
        print(f"| {name} | {value} | {description} | {pc.bias_emoji(score)} |")
    if levels and levels.get("divergence"):
        side = "偏空🔻" if "偏空" in levels["divergence"] else "偏多✅"
        print(f"| RSI背离 | — | {levels['divergence']} | {side} |")

    def funding_text(value):
        return "—" if value is None else f"{value * 100:.4f}%"

    print(
        f"\n**跨所资金费（接口快照）**  OKX {funding_text(okx_funding)} ｜ "
        f"Binance {funding_text(deriv.get('funding_rate_8h'))} ｜ Bybit {funding_text(bybit_funding)}"
    )
    funding_values = [value for value in (okx_funding, deriv.get("funding_rate_8h"), bybit_funding) if value is not None]
    if len(funding_values) >= 2:
        spread = (max(funding_values) - min(funding_values)) * 100
        print(f"乖离 {spread:.4f}%（快照比较；各交易所实际结算周期需自行核实）")

    candidates = []
    if levels and pv:
        sh30, sl30 = levels["swing_high_30"], levels["swing_low_30"]
        sh12, sl12 = levels["swing_high_12"], levels["swing_low_12"]
        atr_value = levels.get("atr14") or 0
        digits = 0 if pv > 100 else 2
        quote = lambda number: f"{number:.{digits}f}"
        unit = atr_value if atr_value > 0 else max((sh30 - sl30) * 0.1, pv * 0.002)
        projected_range = max(sh30 - sl30, 2 * unit)
        confirmation = profile["confirmed_closes"]

        candidates = [
            candidate(
                "低多回踩", f"回踩 {quote(sl12)} 后出现已收盘K企稳", sl12, sl12 - 1.2 * unit,
                [sh12, sh30], rr_value(sh30 - sl12, 1.2 * unit),
            ),
            candidate(
                "突破多", f"{confirmation} 根 {bar} 已收盘K站上 {quote(sh30)}", sh30, sh30 - 1.2 * unit,
                [sh30 + projected_range], rr_value(projected_range, 1.2 * unit),
            ),
            candidate(
                "破位空", f"{confirmation} 根 {bar} 已收盘K收在 {quote(sl12)} 下方", sl12, sl12 + 1.2 * unit,
                [sl12 - projected_range], rr_value(projected_range, 1.2 * unit),
            ),
            candidate(
                "阻力空", f"{confirmation} 根 {bar} 已收盘K在 {quote(sh30)} 下方收回/被拒", sh30, sh30 + 1.2 * unit,
                [sl12], rr_value(sh30 - sl12, 1.2 * unit),
            ),
        ]
        location = (pv - sl30) / projected_range if projected_range > 0 else 0.5
        location_note = (
            "现价靠近30根区间上沿：回踩与确认突破都是候选，不自动否定动量。"
            if location > 0.8 else
            "现价靠近30根区间下沿：反弹与确认破位都是候选，不自动假设反转。"
            if location < 0.2 else "现价位于30根区间中部：候选需由已收盘确认与数据质量筛选。"
        )
        print(
            f"\n**关键结构（已收盘K）** 阻力 {quote(sh30)}/{quote(sh12)} ｜ 现价 {quote(pv)} ｜ "
            f"支撑 {quote(sl12)}/{quote(sl30)} ｜ ATR14 {quote(atr_value)}"
        )
        print(f"位置提示：{location_note}")
        print(
            f"档位：**{profile['name']}** — {profile['label']}；候选初始风险按用户上限的 "
            f"{profile['risk_fraction']:.0%} 估算。"
        )
        print("\n**候选情景（不预设唯一选择；需自行结合上下文）**")
        print("| 候选 | 已收盘确认条件 | 参考进场 | 结构止损(1.2ATR) | 结构目标 | 结构R:R |")
        print("|---|---|---:|---:|---|---:|")
        for item in candidates:
            targets = "→".join(quote(value) for value in item["targets"])
            print(
                f"| {item['name']} | {item['trigger']} | {quote(item['entry'])} | "
                f"{quote(item['stop'])} | {targets} | {rr_text(item['rr_structural'])} |"
            )
        print(f"总开关（结构观察位）{quote(sl12)}：只在已收盘确认后评估，不把实时触价当作成交信号。")

    execution = execution_summary(args, profile, deriv.get("funding_rate_8h"), candidates)
    render_execution_summary(execution)

    drivers = sorted((row for row in rows if row[3] != 0), key=lambda row: -abs(row[3]))[:4]
    if drivers:
        print("\n**结构化证据摘要（留给模型/交易者判断，不强制唯一结论）**")
        print("；".join(f"{name}：{description}" for name, _, description, _ in drivers))
    print("\n⚠️ 技术分析快照，非投资建议；未进行实盘或历史回测。低周期噪音高，任何执行都应核实交易所规则、成本、仓位与杠杆风险。")

    if errors:
        print("\n**数据源错误/缺失（不应被当作中性数据）**")
        for error in errors:
            print("-", error)

    out = {
        "symbol": sym,
        "bar": bar,
        "profile": profile,
        "price": price,
        "structure": levels,
        "okx_funding": okx_funding,
        "bybit_funding": bybit_funding,
        "derivatives": deriv,
        "depth": depth,
        "mtf": [{"tf": tf, "dir": direction, "rsi": rsi_value, "close": close} for tf, direction, rsi_value, close in mtf],
        "resonance": resonance,
        "bias_score": total,
        "bias": bias,
        "data_quality": quality,
        "candidates": candidates,
        "execution_assumptions": execution,
        "errors": errors,
    }
    print("\n----- JSON -----")
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
