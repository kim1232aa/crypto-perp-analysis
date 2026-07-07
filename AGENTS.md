# AGENTS.md — how ANY agent should use this tool

Harness-neutral guide (Claude Code, Codex, OpenClaw, Hermes, OpenAI/LangChain
agents, cron, or a bare terminal). `SKILL.md` is a **cross-agent standard**, so the
same folder auto-discovers in every harness that supports it — only the install
dir differs. The Python is **not** Claude-specific.

| Harness | Skill dir (drop the folder here) | Frontmatter it reads |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `name`, `description` |
| Codex CLI | `~/.codex/skills/` · repo `.codex/skills/` | `name`, `description` (+ optional `agents/openai.yaml`) |
| OpenClaw | `~/.openclaw/skills/` · workspace `skills/` | `name`, `description` |
| Hermes | `~/.hermes/skills/` · project `skills/` | `description` (activation) |

Install helper: `bash install.sh <claude|codex|openclaw|hermes|all|auto>`.
Non-SKILL.md harnesses (LangChain, cron, bare shell): just run the scripts below.

## What it is
Live crypto perpetual-futures long/short analysis. Pure Python 3 stdlib, no deps,
no API keys. Data from public OKX / Binance / Bybit REST endpoints.

## Run it
```bash
python3 scripts/analyze.py ETH 5m      # detailed single-symbol report
python3 scripts/scan.py  BTC,ETH,SOL 15m   # rank a watchlist by score
python3 scripts/alert.py ETH 1785 1796     # price-vs-trigger (loop this every 5m)
python3 scripts/analyze.py --help          # any script: -h prints usage + rubric
```
If exchanges are geo/network blocked: prefix `HTTPS_PROXY=http://<proxy>:<port>`.

## The ONE hard rule: forced, verbatim output
`analyze.py` prints a block delimited by:
```
╔═══════ 报告块 · 必须原样完整输出 ... ═══════╗
   ... 快照 / 多周期共振 / 面板表 / 跨所资金费 / 关键位 / 情景剧本 / 总开关 / 合并结论·建议 ...
╚═══════ 报告块结束 ... ═══════╝
```
**Everything between those markers is MANDATORY output. Reproduce it verbatim.**
Specifically:
- **DO NOT** compress the 面板表 (指标|数值|解读|倾向) into prose bullets or drop rows.
  Keep it a table.
- **DO NOT** drop the 合并结论 / 建议(主策略) / 高胜率 lines — they are the takeaway.
- **DO NOT** invent or alter any number. If the script reports `errors[]`, say which
  source failed and analyze only what you have. Never fabricate to fill a gap.
- You MAY add 2–4 lines of narration *around* the block, and MUST translate/answer
  in the user's language. You may NOT replace the block with your own summary.

## Reading the numbers (rubric)
The script already tags every signal and computes a bias score + recommendation;
this is for your narration, not to recompute:
- **OI × price**: 涨+仓增=多头续涨 · 跌+仓增=空头续跌 · 涨+仓减=轧空反弹(非反转) · 平+仓增=蓄势
- **散户多空比** (contrarian): >1.3 拥挤多→反指偏空 · <0.77 拥挤空→反指偏多。拥挤方的止损=踩踏燃料。
- **大户持仓比** (smart money, 顺势): >1.2 且回升=主力加多 · <0.8 且下降=主力加空。边际变化最重要。
- **taker**: >1.2 主动买盘强 · <0.8 主动卖盘强。**funding**: >0.05%/8h 多头过热(追多有反噬)。
- **RSI**: <30 超卖(反弹概率升) · >70 超买。**背离**领先转折。**ATR**: 止损幅度=1.2×ATR。
- **多周期共振**: 各周期同向=高信心顺势；分歧=区间/转折,轻仓。
- **总开关** = swing_low_12：守住偏多，收破转弱。

## Always
Technical analysis, **not financial advice**. Low timeframes are high-noise.
Every scenario carries a stop-loss; remind the user to control leverage. Prices
are snapshots and move — offer to re-run or monitor with `alert.py` + a 5-min loop.
