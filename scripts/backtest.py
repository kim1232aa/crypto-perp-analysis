#!/usr/bin/env python3
"""Replay a price-execution layer from a local perpetual decision log.

Signals are decisions known at a bar close.  A qualifying signal is attempted
at the next bar open, never on the signal bar.  The replay validates its input,
uses gap-aware stops, marks open positions to market at every bar close, and
reports execution assumptions alongside the result.

Input may be CSV, JSON, or JSONL. Required fields are open/high/low/close;
timestamp (or time) is strongly recommended. Optional fields are side,
signal_score, atr, stop, target, and funding_rate. ``funding_rate`` is a decimal
bar-close funding event: positive rates are paid by longs and received by
shorts. This remains an execution experiment, not historical factor validation.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re

import perp_core as pc


NUMERIC_FIELDS = (
    "open", "high", "low", "close", "atr", "stop", "target",
    "funding_rate", "signal_score",
)


def fnum(value, default=None):
    try:
        if value in (None, "", "-", "—"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def side_of(value):
    if value in (None, "", "-", "—"):
        return 0
    if isinstance(value, bool):
        raise ValueError("side 不能是布尔值")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError("side 必须是有限数")
        return 1 if value > 0 else -1 if value < 0 else 0
    text = str(value).strip().lower()
    if text in {"long", "buy", "多", "1", "+1", "1.0", "+1.0"}:
        return 1
    if text in {"short", "sell", "空", "-1", "-1.0"}:
        return -1
    if text in {"0", "0.0", "flat", "none", "neutral"}:
        return 0
    raise ValueError(f"无法识别 side: {value!r}")


def _timestamp_key(value):
    text = str(value).strip()
    if not text:
        raise ValueError("timestamp 不能为空")
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        number = float(text)
        if not math.isfinite(number):
            raise ValueError("timestamp 必须是有限数")
        return "number", number
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return "datetime", parsed.timestamp()
    except ValueError:
        parts = tuple(
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"(\d+)", text) if part
        )
        return "text", parts


def _finite(value, name, row_number, *, positive=False):
    number = fnum(value)
    if number is None or not math.isfinite(number):
        raise ValueError(f"第 {row_number} 行 {name} 必须是有限数字")
    if positive and number <= 0:
        raise ValueError(f"第 {row_number} 行 {name} 必须大于 0")
    return number


def normalize_rows(rows):
    if not isinstance(rows, list):
        raise ValueError("输入必须是 OHLC 行数组，或包含 bars 数组的 JSON 对象")
    normalized, previous_key = [], None
    for index, raw_row in enumerate(rows):
        row_number = index + 1
        if not isinstance(raw_row, dict):
            raise ValueError(f"第 {row_number} 行必须是对象")
        bar = {
            key: (_finite(raw_row.get(key), key, row_number, positive=key in {"open", "high", "low", "close", "atr", "stop", "target"})
                  if raw_row.get(key) not in (None, "", "-", "—") else None)
            for key in NUMERIC_FIELDS
        }
        if any(bar[key] is None for key in ("open", "high", "low", "close")):
            raise ValueError(f"第 {row_number} 行缺少有效 OHLC")
        if bar["high"] < max(bar["open"], bar["close"]):
            raise ValueError(f"第 {row_number} 行 high 小于 open/close")
        if bar["low"] > min(bar["open"], bar["close"]):
            raise ValueError(f"第 {row_number} 行 low 大于 open/close")

        timestamp = raw_row.get("timestamp", raw_row.get("time", index))
        timestamp_key = _timestamp_key(timestamp)
        if previous_key is not None:
            if timestamp_key[0] != previous_key[0]:
                raise ValueError("timestamp 格式必须一致")
            if timestamp_key[1] <= previous_key[1]:
                raise ValueError(f"第 {row_number} 行 timestamp 必须严格递增")
        previous_key = timestamp_key
        bar["timestamp"] = str(timestamp)
        try:
            bar["side"] = side_of(raw_row.get("side", raw_row.get("signal")))
        except ValueError as exc:
            raise ValueError(f"第 {row_number} 行 {exc}") from exc

        if bar["side"] > 0:
            if bar["stop"] is not None and bar["stop"] >= bar["close"]:
                raise ValueError(f"第 {row_number} 行多单 stop 必须低于信号收盘价")
            if bar["target"] is not None and bar["target"] <= bar["close"]:
                raise ValueError(f"第 {row_number} 行多单 target 必须高于信号收盘价")
        elif bar["side"] < 0:
            if bar["stop"] is not None and bar["stop"] <= bar["close"]:
                raise ValueError(f"第 {row_number} 行空单 stop 必须高于信号收盘价")
            if bar["target"] is not None and bar["target"] >= bar["close"]:
                raise ValueError(f"第 {row_number} 行空单 target 必须低于信号收盘价")
        normalized.append(bar)
    if len(normalized) < 3:
        raise ValueError("至少需要 3 根有效 K 线")
    return normalized


def load_rows(path: Path):
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(raw.splitlines()))
    elif path.suffix.lower() in {".jsonl", ".ndjson"}:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        parsed = json.loads(raw)
        rows = parsed.get("bars", parsed) if isinstance(parsed, dict) else parsed
    return normalize_rows(rows)


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
            smooth = sum(trs) / period
            result.append(smooth)
        else:
            smooth = (smooth * (period - 1) + tr) / period
            result.append(smooth)
        previous_close = row["close"]
    return result


def fill(price, side, entering, slippage_bps):
    rate = slippage_bps / 10_000
    return price * (1 + (side if entering else -side) * rate)


def _validate_parameters(fee_bps, slippage_bps, stop_atr, target_r, max_hold):
    for name, value in (("fee_bps", fee_bps), ("slippage_bps", slippage_bps)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须是有限非负数")
    for name, value in (("stop_atr", stop_atr), ("target_r", target_r)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} 必须是有限正数")
    if isinstance(max_hold, bool) or not isinstance(max_hold, int) or max_hold <= 0:
        raise ValueError("max_hold 必须是正整数")


def _profile(profile):
    config = pc.profile_config(profile)
    score = config.get("min_signal_score")
    if not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
        raise ValueError(f"profile {profile!r} 缺少有效 min_signal_score")
    return config, float(score)


def _update_excursions(position, bar):
    side, entry = position["side"], position["entry_price"]
    adverse_price = bar["low"] if side > 0 else bar["high"]
    favorable_price = bar["high"] if side > 0 else bar["low"]
    position["mae_return"] = min(position["mae_return"], side * (adverse_price / entry - 1))
    position["mfe_return"] = max(position["mfe_return"], side * (favorable_price / entry - 1))


def _funding_at_close(position, bar):
    rate = bar.get("funding_rate")
    if rate is None or rate == 0:
        return
    # Normalize the funding cash flow by entry notional. Positive is a cost.
    position["funding_cost_return"] += position["side"] * rate * (bar["close"] / position["entry_price"])
    position["funding_events"] += 1


def _close_trade(position, bar, reason, reference_price, fee_bps, slippage_bps):
    side, entry = position["side"], position["entry_price"]
    exit_price = fill(reference_price, side, False, slippage_bps)
    gross = side * (exit_price / entry - 1)
    entry_fee = fee_bps / 10_000
    exit_fee = fee_bps / 10_000 * (exit_price / entry)
    fee_return = entry_fee + exit_fee
    total_cost = fee_return + position["funding_cost_return"]
    return {
        "signal_at": position["signal_at"],
        "entry_at": position["entry_at"],
        "exit_at": bar["timestamp"],
        "side": "long" if side > 0 else "short",
        "reason": reason,
        "entry_reference_price": position["entry_reference_price"],
        "entry_price": entry,
        "exit_reference_price": reference_price,
        "exit_price": exit_price,
        "stop": position["stop"],
        "target": position["target"],
        "hold_bars": position["bars_completed"] + 1,
        "gross_return": gross,
        "entry_fee_return": entry_fee,
        "exit_fee_return": exit_fee,
        "fee_return": fee_return,
        "funding_cost_return": position["funding_cost_return"],
        "funding_events": position["funding_events"],
        "cost_return": total_cost,
        "net_return": gross - total_cost,
        "mae_pct": 100 * position["mae_return"],
        "mfe_pct": 100 * position["mfe_return"],
    }


def _summarize(trades, mtm_max_drawdown, ending_mtm_equity):
    equity, peak, closed_dd, returns = 1.0, 1.0, 0.0, []
    for trade in trades:
        equity *= 1 + trade["net_return"]
        peak = max(peak, equity)
        closed_dd = max(closed_dd, 1 - equity / peak)
        returns.append(trade["net_return"])
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_profit, gross_loss = sum(wins), -sum(losses)
    return {
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "expectancy_pct": round(100 * sum(returns) / len(returns), 4) if returns else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "profit_factor_is_infinite": bool(gross_profit and not gross_loss),
        "net_return_pct": round(100 * (equity - 1), 4),
        "ending_mark_to_market_return_pct": round(100 * (ending_mtm_equity - 1), 4),
        "max_drawdown_pct": round(100 * mtm_max_drawdown, 4),
        "mark_to_market_max_drawdown_pct": round(100 * mtm_max_drawdown, 4),
        "closed_trade_max_drawdown_pct": round(100 * closed_dd, 4),
        "worst_trade_mae_pct": round(min((trade["mae_pct"] for trade in trades), default=0.0), 4),
        "best_trade_mfe_pct": round(max((trade["mfe_pct"] for trade in trades), default=0.0), 4),
    }


def run(rows, profile, fee_bps, slippage_bps, stop_atr, target_r, max_hold):
    _validate_parameters(fee_bps, slippage_bps, stop_atr, target_r, max_hold)
    rows = normalize_rows(rows)
    profile_config, min_score = _profile(profile)
    atrs = atr_series(rows)
    trades, skipped_entries, equity_curve = [], [], []
    position = pending = None
    realized_equity = peak_equity = 1.0
    mtm_max_drawdown = 0.0

    def queue_signal(index, bar):
        nonlocal pending
        if not bar["side"]:
            return
        score_raw = bar.get("signal_score")
        score = abs(score_raw if score_raw is not None else 1.0)
        if score < min_score:
            skipped_entries.append({"signal_at": bar["timestamp"], "reason": "below_profile_threshold", "signal_score": score})
            return
        if index >= len(rows) - 1:
            skipped_entries.append({"signal_at": bar["timestamp"], "reason": "end_of_data_no_next_open", "signal_score": score})
            return
        pending = {
            "signal_at": bar["timestamp"], "side": bar["side"], "signal_score": score,
            "atr": bar.get("atr") or atrs[index], "stop": bar.get("stop"), "target": bar.get("target"),
        }

    for index, bar in enumerate(rows):
        if position is None and pending is not None:
            signal, pending = pending, None
            side, open_price = signal["side"], bar["open"]
            stop_raw, target_raw = signal["stop"], signal["target"]
            if stop_raw is not None and ((side > 0 and open_price <= stop_raw) or (side < 0 and open_price >= stop_raw)):
                skipped_entries.append({
                    "signal_at": signal["signal_at"], "entry_at": bar["timestamp"],
                    "reason": "open_beyond_user_stop", "open": open_price, "user_stop": stop_raw,
                })
            elif target_raw is not None and ((side > 0 and open_price >= target_raw) or (side < 0 and open_price <= target_raw)):
                skipped_entries.append({
                    "signal_at": signal["signal_at"], "entry_at": bar["timestamp"],
                    "reason": "open_beyond_user_target", "open": open_price, "user_target": target_raw,
                })
            else:
                entry_price = fill(open_price, side, True, slippage_bps)
                distance = max(signal["atr"], entry_price * 0.002) * stop_atr
                stop = stop_raw if stop_raw is not None else entry_price - side * distance
                target = target_raw if target_raw is not None else entry_price + side * distance * target_r
                if not ((side > 0 and stop < entry_price < target) or (side < 0 and target < entry_price < stop)):
                    skipped_entries.append({
                        "signal_at": signal["signal_at"], "entry_at": bar["timestamp"],
                        "reason": "user_levels_invalid_after_entry", "entry_price": entry_price,
                        "user_stop": stop_raw, "user_target": target_raw,
                    })
                else:
                    position = {
                        "signal_at": signal["signal_at"], "entry_at": bar["timestamp"], "side": side,
                        "entry_reference_price": open_price, "entry_price": entry_price,
                        "stop": stop, "target": target, "bars_completed": 0,
                        "funding_cost_return": 0.0, "funding_events": 0,
                        "mae_return": 0.0, "mfe_return": 0.0, "equity_before": realized_equity,
                    }

        if position is not None:
            _update_excursions(position, bar)
            side = position["side"]
            stop_gap = (side > 0 and bar["open"] <= position["stop"]) or (side < 0 and bar["open"] >= position["stop"])
            target_gap = (side > 0 and bar["open"] >= position["target"]) or (side < 0 and bar["open"] <= position["target"])
            stop_hit = (side > 0 and bar["low"] <= position["stop"]) or (side < 0 and bar["high"] >= position["stop"])
            target_hit = (side > 0 and bar["high"] >= position["target"]) or (side < 0 and bar["low"] <= position["target"])
            reason = reference_price = None
            if stop_gap:
                reason, reference_price = "stop_gap", bar["open"]
            elif target_gap:
                reason, reference_price = "target_gap", position["target"]
            elif stop_hit:
                reason, reference_price = "stop", position["stop"]
            elif target_hit:
                reason, reference_price = "target", position["target"]
            elif position["bars_completed"] + 1 >= max_hold:
                _funding_at_close(position, bar)
                reason, reference_price = "time", bar["close"]
            elif index == len(rows) - 1:
                _funding_at_close(position, bar)
                reason, reference_price = "end_of_data", bar["close"]
            else:
                _funding_at_close(position, bar)

            if reason is not None:
                trade = _close_trade(position, bar, reason, reference_price, fee_bps, slippage_bps)
                trades.append(trade)
                realized_equity *= 1 + trade["net_return"]
                position = None
            else:
                position["bars_completed"] += 1

        if position is None:
            mark_equity, state = realized_equity, "flat"
        else:
            mark_gross = position["side"] * (bar["close"] / position["entry_price"] - 1)
            mark_net = mark_gross - fee_bps / 10_000 - position["funding_cost_return"]
            mark_equity = position["equity_before"] * (1 + mark_net)
            state = "long" if position["side"] > 0 else "short"
        peak_equity = max(peak_equity, mark_equity)
        drawdown = 1 - mark_equity / peak_equity
        mtm_max_drawdown = max(mtm_max_drawdown, drawdown)
        equity_curve.append({
            "timestamp": bar["timestamp"], "equity": mark_equity,
            "drawdown_pct": 100 * drawdown, "position": state,
        })

        if position is None:
            queue_signal(index, bar)

    ending_mtm_equity = equity_curve[-1]["equity"] if equity_curve else realized_equity
    return {
        "config": {
            "profile": profile,
            "profile_mapping": profile_config,
            "signal_score_mapping": "absolute signal_score; missing signal_score defaults to 1.0",
            "min_signal_score": min_score,
            "fee_bps_each_way": fee_bps,
            "slippage_bps_each_way": slippage_bps,
            "stop_atr": stop_atr,
            "target_r": target_r,
            "max_hold_bars": max_hold,
            "position_notional_fraction": 1.0,
            "position_sizing": "each trade compounds a full-equity 1x price return",
            "funding_rate_unit": "decimal bar-close event; positive paid by longs, negative paid by shorts",
            "funding_timing": "charged only when the position survives to that bar close (including time/end exits)",
            "intrabar_collision": "stop before target when both touch and the open resolves neither",
            "end_of_data": "close at the final recorded close with exit slippage and fee",
            "limitations": "no liquidation, leverage, partial fills, contract multipliers, or historical factor reconstruction",
        },
        "summary": _summarize(trades, mtm_max_drawdown, ending_mtm_equity),
        "skipped_entries": skipped_entries,
        "trades": trades,
        "equity_curve": equity_curve,
    }


def self_test():
    rows = [
        {"timestamp": "t0", "open": 100, "high": 101, "low": 99, "close": 100, "side": 1, "signal_score": 3},
        {"timestamp": "t1", "open": 100, "high": 103, "low": 99, "close": 102, "side": 0},
        {"timestamp": "t2", "open": 102, "high": 105, "low": 101, "close": 104, "side": 0},
    ]
    result = run(rows, "balanced", 0, 0, 1, 2, 10)
    assert result["trades"][0]["reason"] == "target"


def _non_negative_arg(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("必须是有限非负数")
    return number


def _positive_arg(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("必须是有限正数")
    return number


def _positive_int_arg(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是正整数") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="OHLC decision log (.csv/.json/.jsonl)")
    parser.add_argument("--profile", choices=tuple(pc.PROFILES), default="balanced")
    parser.add_argument("--fee-bps", type=_non_negative_arg, default=5.0)
    parser.add_argument("--slippage-bps", type=_non_negative_arg, default=3.0)
    parser.add_argument("--stop-atr", type=_positive_arg, default=1.2)
    parser.add_argument("--target-r", type=_positive_arg, default=2.0)
    parser.add_argument("--max-hold-bars", type=_positive_int_arg, default=48)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("backtest self-test: PASS")
        return
    if not args.input:
        parser.error("请提供输入文件，或运行 --self-test")
    result = run(load_rows(Path(args.input)), args.profile, args.fee_bps, args.slippage_bps,
                 args.stop_atr, args.target_r, args.max_hold_bars)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
