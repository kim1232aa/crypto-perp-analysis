# crypto-perp-analysis

A [Claude Code](https://claude.com/claude-code) **Skill** that turns live crypto
perpetual-futures data into an actionable long/short read — with concrete
entry / stop / target scenarios. Built to stop weaker agents from **hallucinating
prices and indicators**: every number comes from a fetch script, and failed
sources are reported explicitly instead of invented.

## What it does

- **Price & structure** — OKX candles: swing highs/lows, EMA9/21, **RSI14 +
  divergence**, **ATR14** (used for volatility-based stops).
- **Multi-timeframe resonance** — auto-reads 5m / 15m / 1H / 4H alignment for
  confidence (共振 = high-confidence trend; divergence = range/turning).
- **Derivatives (Binance)** — open interest trend, funding rate, basis,
  retail long/short ratio (contrarian), top-trader account & **position**
  ratios (smart-money), taker buy/sell flow.
- **Orderbook imbalance** — OKX ±0.5% depth bid/ask pressure.
- **Cross-exchange funding** — OKX / Binance / Bybit side by side.
- **Signal tagging + bias score + trade scenarios** — all computed in-script, so
  output is consistent no matter which agent runs it.

Works for any `{SYMBOL}-USDT` perpetual (ETH, BTC, SOL, BNB, XRP, DOGE, …).

## Tools (`scripts/`)

| Script | Purpose |
|---|---|
| `analyze.py <SYM> <BAR>` | Detailed single-symbol report (primary tool) |
| `scan.py [SYM,...] [BAR]` | Batch-rank a watchlist by score to find setups |
| `alert.py SYM SUPPORT RESISTANCE` | One-shot price-vs-trigger check (wire to `/loop` for monitoring) |
| `perp_core.py` | Shared library (fetch + indicators + tagging). Not run directly. |

```bash
python3 scripts/analyze.py ETH 5m
python3 scripts/scan.py BTC,ETH,SOL,BNB,XRP,DOGE 15m
python3 scripts/alert.py ETH 1785 1796
```

- **Python stdlib only** — no dependencies.
- Respects `HTTPS_PROXY` / `HTTP_PROXY` if the exchanges are geo/network blocked.
- Data comes from **public** OKX / Binance / Bybit REST endpoints (no API keys).

## Install

**One-liner** (clone + self-check):
```bash
curl -fsSL https://raw.githubusercontent.com/kim1232aa/crypto-perp-analysis/main/install.sh | bash
```

**Or manually:**
```bash
mkdir -p ~/.claude/skills
git clone https://github.com/kim1232aa/crypto-perp-analysis.git \
  ~/.claude/skills/crypto-perp-analysis
# verify — should print a live ETH report with real numbers and no errors
python3 ~/.claude/skills/crypto-perp-analysis/scripts/analyze.py ETH 5m
```

No dependencies, no API keys — Python 3 stdlib only. If the exchanges are
geo/network blocked, prefix with `HTTPS_PROXY=http://<your-proxy>:<port>`.

After install, reload Claude Code (restart the session) so it discovers the
skill, then ask for a 多空分析 / long-short read on any perp — it triggers
automatically. Or run the scripts directly (see **Tools** above).

## Not on Claude Code?

The scripts are plain Python and work in **any** harness (Hermes, Codex, OpenAI/
LangChain agents, cron, bare terminal) — nothing is Claude-specific except the
`SKILL.md` auto-trigger. See **[AGENTS.md](AGENTS.md)** for the harness-neutral
usage guide, or just run `python3 scripts/analyze.py --help`. Key rule for any
agent: the report block between the `╔═╗` markers is **mandatory verbatim
output** — don't summarize the panel table or drop the conclusion.

## Disclaimer

Technical analysis only — **not financial advice.** Low timeframes (5m/15m) are
high-noise; always use a stop-loss and control leverage. Numbers are live
snapshots and move fast. Scenario R:R is structural math, not a promised win rate.

## License

MIT
