---
name: crypto-perp-analysis
description: >-
  永续合约结构化证据快照。读取 OKX/Binance/Bybit 公开数据，输出仅由已收盘
  K 线计算的结构、OI/资金费/账户比/taker、数据质量、多个候选情景和执行假设。
  可扫描币种、监控实时预警或已收盘确认。用于行情/多空/资金费/OI/永续合约分析请求。
---

# Crypto Perp Analysis

这是一个实时数据证据工具，不是自动交易系统、收益承诺或完整回测。它输出可审计的数值、数据来源缺口和候选情景，供模型与用户结合上下文自行判断；不要把机械评分、R:R 或某个触发条件说成胜率。

## 基本规则

1. **无需设置。** 不需要 API key、密钥、`PERP_API_KEY` 或 `pip install`；仅用 Python 标准库和公开 OKX/Binance/Bybit REST 接口。网络受限时可使用 `HTTPS_PROXY=http://<proxy>:<port>`。
2. **先取真实数据。** 运行脚本后再引用价格、指标、资金费或价位；不能补造缺失数字。
3. **尊重数据质量。** `NO_TRADE` 代表关键现价、已收盘结构 K、多周期、时间连续性/新鲜度或核心衍生品字段不足；此时聚合方向/评分为 `null`，候选和仓位数组为空，只能说明原始证据。`READY` 只表示本次字段完整且及时，不表示回测有效或应交易。
4. **模型可自由组织答复。** 可摘要、比较、解释或请求更多上下文；无需逐字转发脚本，也不应把候选情景包装为唯一结论。
5. **说清限制。** 快照会过时，低周期噪音高；费用、滑点、资金费、合约规格、流动性、仓位和杠杆都需用户自行核实。

## 运行

```bash
# 旧的基础命令继续可用
python3 <skill_dir>/scripts/analyze.py ETH 5m

# 三种确认/风险提示档位（默认 balanced）
python3 <skill_dir>/scripts/analyze.py ETH 5m --profile balanced
python3 <skill_dir>/scripts/analyze.py ETH 5m --profile conservative
python3 <skill_dir>/scripts/analyze.py ETH 5m --profile active

# 显式给出执行估算输入；无输入时脚本不会暗设账户风险偏好
python3 <skill_dir>/scripts/analyze.py ETH 5m --fee-bps 4 --slippage-bps 2 \
  --risk-pct 0.5 --account-equity 10000

# 只让核心数据完整的币参与机械评分排名
python3 <skill_dir>/scripts/scan.py BTC,ETH,SOL 15m

# 默认：实时越界预警，绝非确认触发
python3 <skill_dir>/scripts/alert.py ETH 1785 1796

# 只有显式指定周期时，才按已收盘 K 确认
python3 <skill_dir>/scripts/alert.py ETH 1785 1796 --confirm-closed 5m --profile balanced
```

## 已收盘 K 与多周期

`okx_candles()` 只将 OKX `confirm=1` 的 K 线送入 EMA、RSI、ATR、支撑阻力和多周期判断，并在 JSON 的 `meta` 保留时间戳、确认状态、连续性/新鲜度与剔除数量。主周期机械结构评分也使用最后已收盘价；实时 ticker 仅用于位置展示。

完整“多周期共振”要求 5m、15m、1H、4H 四个**已收盘**周期都可用且同向。任何一个周期缺失时，报告必须写“数据不完整”，不能称高信心共振。

## 数据来源与解释边界

- 价格、K 线、盘口来自 **OKX**；OI、资金费、全站账户比、头部账户/持仓比、taker 来自 **Binance**；另一资金费快照来自 **Bybit**。输出保留各源时间字段；资金费按各所当前结算周期展示，并额外换算为 8 小时等效值后比较。它们仍不是同一交易所/同一时刻的可交易订单簿。
- Binance `globalLongShortAccountRatio` 应称为“**Binance 全站账户比**”，不能泛称散户；`topLongShortPositionRatio`/账户比应称为“**Binance 头部…比（平台口径）**”，不能等同于主力或 smart money 身份。
- 手工评分将 OI×价格、账户比、taker、结构、RSI、资金费和盘口转为方向线索，**不是**历史校准的概率模型。

## 候选情景和 Profile

报告会列出回踩、确认突破、确认破位、阻力被拒等结构候选。它们都需要已收盘 K 或额外上下文确认，且不预设唯一选择。

| Profile | 需要的已收盘确认 | 相对用户风险上限 | 说明 |
|---|---:|---:|---|
| `conservative` | 2 根 | 50% | 回踩优先、较小初始风险预算 |
| `balanced` | 1 根 | 75% | 回踩和突破均为候选 |
| `active` | 1 根 | 100% | 更及时观察已确认动量；实时触价仍不是成交 |

若未传 `--risk-pct`，脚本只显示仓位公式；若同时传入 `--risk-pct` 与 `--account-equity`，才给出一个未含合约乘数/清算/部分成交的近似值。费用、滑点和资金费始终只是输入假设，R:R 是结构距离，不能当作费用后收益。

## 如何回应用户

推荐做法：

1. 说明快照时间性和 `data_quality` 状态；当状态为 `NO_TRADE` 时，先解释缺失来源。
2. 先读取版本化 JSON 的 `data_quality.status`、`can_form_direction`、`reference_levels` 与 `candidates`，再解释信号分歧与来源差异；不要改变脚本取得的数字。
3. 将候选情景描述为条件，而不是命令；可补充用户的持仓周期、风险上限或实际费用后再讨论。
4. 以用户语言提醒：技术分析不是投资建议，任何交易应先确认费用、杠杆和止损可执行性。

## 本地 OHLC 回放（有限验证）

```bash
python3 <skill_dir>/scripts/backtest.py path/to/decision-log.csv --profile balanced \
  --fee-bps 5 --slippage-bps 3
python3 <skill_dir>/scripts/backtest.py --self-test
```

`backtest.py` 是**本地 OHLC 决策日志的价格执行层回放**：信号在一根 K 收盘时已知，最早下一根开盘成交；跳空止损按开盘处理，并输出逐 K 收盘盯市回撤、MAE/MFE、手续费、滑点和逐 K 资金费。它不是完整因子验证，不提供历史 OI/账户比/盘口，且不模拟部分成交、清算、合约乘数或真实交易所限制；不能由此声称实时因子有 alpha。

## 自检

```bash
python3 -m unittest discover -s <skill_dir>/tests -v
python3 <skill_dir>/scripts/backtest.py --self-test
```
