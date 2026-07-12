# AGENTS.md — cross-agent usage

This repository is a live perpetual-futures **evidence tool**, usable from Claude Code, Codex, OpenClaw, Hermes, cron, LangChain, or a bare terminal. `SKILL.md` is the cross-agent guide; the Python scripts use only the standard library and public OKX/Binance/Bybit endpoints.

| Harness | Skill directory |
|---|---|
| Claude Code | `~/.claude/skills/` |
| Codex CLI | `~/.codex/skills/` or repo `.codex/skills/` |
| OpenClaw | `~/.openclaw/skills/` or workspace `skills/` |
| Hermes | `~/.hermes/skills/` or workspace `skills/` |

Install with `bash install.sh <claude|codex|openclaw|hermes|all|auto>`.

## Setup

**No API key, secret, `PERP_API_KEY`, pip install, or `requests` dependency exists.** If exchange access is network/geo blocked, retry with `HTTPS_PROXY=http://<proxy>:<port>`; do not request credentials.

## Commands

```bash
python3 scripts/analyze.py ETH 5m
python3 scripts/analyze.py ETH 5m --profile balanced
python3 scripts/analyze.py ETH 5m --fee-bps 4 --slippage-bps 2 \
  --risk-pct 0.5 --account-equity 10000
python3 scripts/scan.py BTC,ETH,SOL 15m

# Live price only: warning, never an automatically confirmed trigger
python3 scripts/alert.py ETH 1785 1796

# Opt in to completed-candle confirmation
python3 scripts/alert.py ETH 1785 1796 --confirm-closed 5m --profile balanced
```

`conservative` requires two closed candles, uses 50% of a user-supplied risk cap and a recorded backtest score threshold of 3; `balanced` (default) uses one/75%/1; `active` uses one/100%/0.25. The tool never assumes a risk percentage: omit `--risk-pct` to receive only the sizing formula.

## Data and response rules

- K-derived numbers use **only OKX `confirm=1` closed candles**. JSON retains timestamps, continuity/freshness metadata and the count of discarded open candles. Stale, duplicated or discontinuous core series fail the data gate.
- Treat `NO_TRADE` as a hard data gate: `bias`, aggregate resonance and score become `null`, while candidates and sizing are empty. Raw source evidence remains available for model/user inspection. `CAUTION` means auxiliary inputs are missing. `READY` means fields are present and timely, **not** that the setup is backtested or actionable.
- The versioned JSON exposes stable top-level `asset_class`, `instrument`, `as_of`, `profile`, `data_quality`, `can_form_direction`, `can_size`, `reference_levels`, `candidates`, and `no_trade` fields. Read the gate before interpreting evidence.
- Never invent a price, indicator, funding rate or source that is missing. Explain source failures and data timing.
- The output is structured evidence, not a mandatory verbatim response. You may summarize, compare or reason from it in the user's language, but preserve the values you cite and leave room for model/user judgment.
- Do not label a condition as a high-probability/winning trade. Candidate scenarios are conditions; they do not select a sole action.
- Use source-accurate terms: Binance `globalLongShortAccountRatio` is “Binance 全站账户比”, not necessarily retail; Binance top-account/top-position ratios are platform-defined ratios, not proof of “主力” identity.

## Execution caveats

`analyze.py` displays user-overridable fee/slippage assumptions, each venue's current funding interval, an 8-hour-equivalent comparison and optional sizing math. These are **not backtest results**, fills or an exchange quote. R:R is structural distance and excludes unknown execution effects unless explicitly modelled.

`scripts/backtest.py` can replay the **price-execution layer of a local OHLC decision log** (signal at close, fill no earlier than next open), with gap-aware stops, bar-close mark-to-market drawdown, MAE/MFE and split fee/slippage/funding inputs:

```bash
python3 scripts/backtest.py path/to/decision-log.csv --profile balanced
python3 scripts/backtest.py --self-test
```

It is not full factor validation: it does not reconstruct historical OI, account ratios or order books, and it omits partial fills, liquidation, contract multipliers and venue restrictions.

## Always

Technical analysis is not investment advice. Low timeframes are noisy; remind users that prices are snapshots and that they must verify exchange rules, costs, leverage, position size and liquidation risk.
