#!/usr/bin/env python3
"""Replay a price-only perpetual strategy from a local OHLC decision log.

This is an execution-layer experiment, not a claim that the live signal panel
has alpha. It uses decisions known at a bar close and fills no earlier than the
next bar open. Input is CSV, JSON, or JSONL with OHLC columns plus optional
side (long/short), signal_score, atr, stop, target and funding_rate.

Profiles select the minimum recorded signal_score: conservative=3, balanced=1,
active=0.25.  Costs are explicit: fee, slippage and per-bar funding. The script
does not model liquidation, partial fills, or unavailable historical derivatives
data, so those must not be inferred from its results.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


PROFILE_MIN_SCORE = {"conservative": 3.0, "balanced": 1.0, "active": 0.25}


def fnum(value, default=None):
    try:
        if value in (None, "", "-", "—"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def side_of(value):
    if isinstance(value, (int, float)):
        return 1 if value > 0 else -1 if value < 0 else 0
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "多", "1", "+1"}:
        return 1
    if text in {"short", "sell", "空", "-1"}:
        return -1
    return 0


def load_rows(path: Path):
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(raw.splitlines()))
    elif path.suffix.lower() in {".jsonl", ".ndjson"}:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        parsed = json.loads(raw)
        rows = parsed.get("bars", parsed) if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        raise ValueError("输入必须是 OHLC 行数组，或包含 bars 数组的 JSON 对象")
    out = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        bar = {key: fnum(row.get(key)) for key in ("open", "high", "low", "close", "atr", "stop", "target", "funding_rate", "signal_score")}
        if any(bar[key] is None or bar[key] <= 0 for key in ("open", "high", "low", "close")):
            raise ValueError(f"第 {index + 1} 行缺少有效 OHLC")
        bar["timestamp"] = str(row.get("timestamp", row.get("time", index)))
        bar["side"] = side_of(row.get("side", row.get("signal")))
        out.append(bar)
    if len(out) < 3:
        raise ValueError("至少需要 3 根有效 K 线")
    return out


def atr_series(rows, period=14):
    trs, result, previous_close, smooth = [], [], None, None
    for row in rows:
        tr = row["high"] - row["low"] if previous_close is None else max(
            row["high"] - row["low"], abs(row["high"] - previous_close), abs(row["low"] - previous_close)
        )
        trs.append(tr)
        if len(trs) < period:
            result.append(sum(trs) / len(trs))
        elif len(trs) == period:
            smooth = sum(trs) / period; result.append(smooth)
        else:
            smooth = (smooth * (period - 1) + tr) / period; result.append(smooth)
        previous_close = row["close"]
    return result


def fill(price, side, entering, slippage_bps):
    rate = slippage_bps / 10_000
    return price * (1 + (side if entering else -side) * rate)


def summarize(trades):
    equity, peak, max_dd, returns = 1.0, 1.0, 0.0, []
    for trade in trades:
        equity *= 1 + trade["net_return"]
        peak = max(peak, equity)
        max_dd = max(max_dd, 1 - equity / peak)
        returns.append(trade["net_return"])
    wins, losses = [x for x in returns if x > 0], [x for x in returns if x < 0]
    gross_profit, gross_loss = sum(wins), -sum(losses)
    return {"trades": len(trades), "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
            "expectancy_pct": round(100 * sum(returns) / len(returns), 4) if returns else None,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (None if not gross_profit else "inf"),
            "net_return_pct": round(100 * (equity - 1), 4), "max_drawdown_pct": round(100 * max_dd, 4)}


def run(rows, profile, fee_bps, slippage_bps, stop_atr, target_r, max_hold):
    atrs, trades, position = atr_series(rows), [], None
    min_score = PROFILE_MIN_SCORE[profile]
    for i, bar in enumerate(rows):
        if position is None:
            if i >= len(rows) - 1 or not bar["side"]:
                continue
            score_raw = bar.get("signal_score")
            score = abs(score_raw if score_raw is not None else 1.0)
            if score < min_score:
                continue
            side, next_bar = bar["side"], rows[i + 1]
            entry = fill(next_bar["open"], side, True, slippage_bps)
            distance = max(bar.get("atr") or atrs[i], entry * 0.002) * stop_atr
            stop_raw, target_raw = bar.get("stop"), bar.get("target")
            valid_stop = stop_raw and ((side > 0 and stop_raw < entry) or (side < 0 and stop_raw > entry))
            valid_target = target_raw and ((side > 0 and target_raw > entry) or (side < 0 and target_raw < entry))
            stop = stop_raw if valid_stop else entry - side * distance
            target = target_raw if valid_target else entry + side * distance * target_r
            position = {"entry_at": next_bar["timestamp"], "entry": entry, "side": side, "stop": stop,
                        "target": target, "age": 0, "funding": 0.0}
            continue
        position["age"] += 1
        position["funding"] += position["side"] * (bar.get("funding_rate") or 0.0)
        side = position["side"]
        stop_hit = bar["low"] <= position["stop"] if side > 0 else bar["high"] >= position["stop"]
        target_hit = bar["high"] >= position["target"] if side > 0 else bar["low"] <= position["target"]
        # If both touch within one candle, stop first is the conservative convention.
        if stop_hit:
            reason, exit_price = "stop", position["stop"]
        elif target_hit:
            reason, exit_price = "target", position["target"]
        elif position["age"] >= max_hold:
            reason, exit_price = "time", bar["close"]
        else:
            continue
        exit_fill = fill(exit_price, side, False, slippage_bps)
        gross = side * (exit_fill / position["entry"] - 1)
        costs = 2 * fee_bps / 10_000 + position["funding"]
        trades.append({"entry_at": position["entry_at"], "exit_at": bar["timestamp"],
                       "side": "long" if side > 0 else "short", "reason": reason,
                       "gross_return": gross, "cost_return": costs, "net_return": gross - costs})
        position = None
    if position is not None:
        last, side = rows[-1], position["side"]
        exit_fill = fill(last["close"], side, False, slippage_bps)
        gross = side * (exit_fill / position["entry"] - 1)
        costs = 2 * fee_bps / 10_000 + position["funding"]
        trades.append({"entry_at": position["entry_at"], "exit_at": last["timestamp"],
                       "side": "long" if side > 0 else "short", "reason": "end_of_data",
                       "gross_return": gross, "cost_return": costs, "net_return": gross - costs})
    return {"summary": summarize(trades), "trades": trades}


def self_test():
    rows = [
        {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100, "side": 1, "signal_score": 3},
        {"timestamp": "t1", "open": 100, "high": 103, "low": 99, "close": 102, "side": 0},
        {"timestamp": "t2", "open": 102, "high": 105, "low": 101, "close": 104, "side": 0},
    ]
    assert run(rows, "balanced", 0, 0, 1, 2, 10)["trades"][0]["reason"] == "target"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="OHLC decision log (.csv/.json/.jsonl)")
    parser.add_argument("--profile", choices=PROFILE_MIN_SCORE, default="balanced")
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=3.0)
    parser.add_argument("--stop-atr", type=float, default=1.2)
    parser.add_argument("--target-r", type=float, default=2.0)
    parser.add_argument("--max-hold-bars", type=int, default=48)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(); print("backtest self-test: PASS"); return
    if not args.input:
        parser.error("请提供输入文件，或运行 --self-test")
    result = run(load_rows(Path(args.input)), args.profile, args.fee_bps, args.slippage_bps,
                 args.stop_atr, args.target_r, args.max_hold)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
