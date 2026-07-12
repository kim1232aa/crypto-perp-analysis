# crypto-perp-analysis

一个纯 Python 标准库的永续合约**结构化证据快照**工具。它从 OKX、Binance、Bybit 的公开接口读取价格、已收盘 K 线、OI、资金费、多空比、taker 和盘口数据，输出可审计的指标、数据质量和多个候选情景。

它不是自动交易器，也不是已验证的盈利策略或完整回测系统。输出不强制唯一结论；模型和交易者应基于结构化证据、市场上下文及自身风险约束判断。

## 核心原则

- **只用 OKX `confirm=1` 的已收盘 K 线**计算 EMA、RSI、ATR、结构位、主周期评分和多周期方向；JSON 中保留时间戳、连续性/新鲜度及被剔除的未收盘 K 数量。
- **数据完整性先于方向**：`NO_TRADE` 表示价格、闭合结构 K、多周期、时效/连续性或核心衍生品数据不足；此时 `bias/score/resonance=null`，候选与仓位为空。`CAUTION` 表示辅助来源缺失；`READY` 只表示本次数据完整及时，不代表应该交易或策略有效。
- **实时价格越界只是预警**。`alert.py` 只有在显式传入 `--confirm-closed BAR` 后，才会按已收盘 K 给出确认突破/破位。
- **费用、滑点、资金费和仓位只是输入估算**，不是成交承诺或实盘回测结果。

## 使用

```bash
# 结构化证据 + 候选情景；旧命令仍兼容
python3 scripts/analyze.py ETH 5m

# 档位只改变确认/风险提示，不篡改市场数据
python3 scripts/analyze.py BTC 15m --profile balanced
python3 scripts/analyze.py BTC 15m --profile conservative
python3 scripts/analyze.py BTC 15m --profile active

# 覆盖成本假设；给定账户权益后打印近似仓位公式结果
python3 scripts/analyze.py ETH 5m --fee-bps 4 --slippage-bps 2 \
  --risk-pct 0.5 --account-equity 10000

# 多币扫描：同样检查 5m/15m/1H/4H、核心衍生品和辅助源；只有 READY 参与排名
python3 scripts/scan.py BTC,ETH,SOL 15m

# 默认仅实时预警，不是交易触发
python3 scripts/alert.py ETH 1785 1796

# 显式要求以已收盘 5m K 确认（可接入定时任务）
python3 scripts/alert.py ETH 1785 1796 --confirm-closed 5m --profile balanced
```

无需 API key、密钥或第三方依赖。网络/地区限制时可使用 `HTTPS_PROXY=http://<proxy>:<port>`。

### Profile

| 档位 | 已收盘确认 | 相对用户风险上限 | 用途 |
|---|---:|---:|---|
| `conservative` | 2 根 | 50% | 回踩优先、降低初始风险预算 |
| `balanced`（默认） | 1 根 | 75% | 回踩和确认突破均作为候选 |
| `active` | 1 根 | 100% | 更及时地观察已确认动量，仍不以实时触价成交 |

档位不会提高杠杆，也不代表收益/胜率；应在样本外评估后再决定是否采用。

## 输出说明

`analyze.py` 输出三层信息：

1. **数据质量**：核心缺失时明确给出 `NO_TRADE`，不会把失败的接口当作中性数据或将 funding 显示为零。
2. **结构化证据**：多周期表、机械评分、带来源时间的衍生品面板、按真实结算周期及 8h 等效值展示的跨所资金费、已收盘结构位。机械评分是手工规则，不是概率预测。
3. **候选情景与执行估算**：回踩、确认突破、确认破位、阻力被拒等条件；费用、滑点、资金费、风险预算和近似仓位公式会单独显示。候选情景并非指令，R:R 仅为结构距离，未替代实际成交成本。

最后输出带 `schema_version` 的 JSON。稳定顶层字段包含 `asset_class`、`instrument`、`as_of`、`profile`、`data_quality`、`can_form_direction`、`can_size`、`reference_levels`、`candidates` 和 `no_trade`，方便其他程序或模型自由使用证据。`NO_TRADE` 时方向、候选和仓位均为空。

## 本地 OHLC 回放（有限验证）

`scripts/backtest.py` 用本地 CSV/JSON/JSONL 的 OHLC **决策日志**回放价格执行层：决策在一根 K 收盘时已知，最早从下一根开盘成交；跳空穿越止损按开盘处理，并输出逐 K 收盘盯市权益、MTM/已平仓回撤、MAE/MFE，以及分拆的手续费、滑点和逐 K 资金费。

```bash
python3 scripts/backtest.py path/to/decision-log.csv --profile balanced \
  --fee-bps 5 --slippage-bps 3
python3 scripts/backtest.py --self-test
```

这不是完整因子验证：它不补齐历史 OI/多空比/盘口，不模拟部分成交、清算、合约乘数或真实交易所规则。不要据此宣称实时面板有 alpha；仍应做跨币种、跨 regime 的样本外和 walk-forward 验证。

## 安装

```bash
git clone --depth 1 https://github.com/kim1232aa/crypto-perp-analysis.git
cd crypto-perp-analysis
bash install.sh auto
```

或手动克隆：

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/kim1232aa/crypto-perp-analysis.git \
  ~/.claude/skills/crypto-perp-analysis
python3 ~/.claude/skills/crypto-perp-analysis/scripts/analyze.py ETH 5m
```

同一文件夹可用于 Claude Code、Codex、OpenClaw 和 Hermes；安装后重启相应会话以发现 skill。

## 自检

```bash
python3 -m unittest discover -s tests -v
python3 scripts/backtest.py --self-test
```

测试覆盖未确认 OKX K 的剔除、数据缺失时的 `NO_TRADE`、缺失 funding 的显示、alert 的预警/收盘确认边界，以及 profile 不输出“高胜率”或单一策略指令。

## 免责声明

技术分析快照，不构成投资建议。低周期噪音大；请自行核实交易所结算周期、手续费、滑点、合约规格、流动性、仓位、杠杆和清算风险。

## License

MIT
