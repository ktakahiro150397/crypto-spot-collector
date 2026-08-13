# ETH perpetual SAR parameter analysis

## Decision

There is no parameter set in this experiment with enough out-of-sample
evidence to claim positive expected return. The strongest provisional
configuration is:

- signal timeframe: `1h`;
- take profit: `25%` ROE;
- stop loss: `1.5%` ROE;
- trailing activation: `3%` ROE; and
- trailing evaluation interval: `3m`.

It is a useful research default because it materially outperformed the
existing `30m / TP 15 / SL 3 / trail 7` baseline, but it should not replace
the production configuration on the strength of this test alone.

## Experimental design

The input is checksum-verified Binance USD-M `ETHUSDT` 1-minute perpetual
kline data used as a proxy for the Hyperliquid strategy. Parameters were
selected only on January through June 2025. July through October 2025 was
kept closed until the training nominees were locked. A second, newly fetched
November 2025 through July 2026 series was then used as confirmation without
re-selecting parameters.

The coarse grid contains 108 combinations:

- timeframe: `5m`, `15m`, `30m`, `1h`, `2h`, `4h`;
- TP ROE: `8`, `15`, `25`;
- SL ROE: `1.5`, `3`, `6`; and
- trailing activation ROE: `3`, `7`.

All runs use initial equity `1000`, order notional `12`, leverage `3`, four
consecutive SAR candles for entry, two opposite SAR candles for close, a
three-minute trailing interval, `5 bps` taker fee, and `1 bp` adverse
slippage. Funding is not present in the kline source and is excluded.

The robust training score is:

```text
training return - training max drawdown - population stddev(monthly returns)
```

The maximum-return and robust-score selectors independently chose the same
configuration.

## Results

| configuration | Jan-Jun 2025 training | Jul-Oct 2025 holdout | Nov 2025-Jul 2026 confirmation | max DD in confirmation | confirmation profit factor |
|---|---:|---:|---:|---:|---:|
| existing baseline | -0.3187% | -0.1664% | -1.4220% | 1.5506% | 0.7644 |
| provisional candidate | +0.4202% | -0.3220% | -0.1437% | 0.5376% | 0.9331 |

The candidate had a `1.2832` training profit factor and `0.2370%` training
maximum drawdown. In the first holdout its profit factor fell to `0.7217`.
In the independent nine-month confirmation it remained below break-even, but
lost roughly one tenth as much as the baseline and had about one third of the
drawdown.

The training result supports the timeframe more strongly than the exact
protection values. Seventeen of the 18 one-hour combinations were profitable,
with median return `+0.1812%`. Every 15-minute and two-hour combination was
negative. The five-minute group had median return `-5.2386%` and a median of
about 3,907 trades, showing severe turnover and cost drag under the stated
fee assumptions.

Within the one-hour group, TP `25` and SL `1.5` had the best median returns
across their neighboring combinations. Trailing activation was less decisive:
`7` had the better group median, while the selected TP/SL interaction favored
`3`. Treat the exact trailing threshold as unresolved.

## Interpretation and next gate

The defensible conclusion is to continue research around the one-hour family,
not to claim that the winning training tuple is profitable. Its negative
results in both later periods are direct evidence against deployment. The
next decision gate should require positive walk-forward performance across
more instruments or a later untouched period, with funding and
Hyperliquid-specific fee/execution assumptions included.

## Confirmation reproduction

Fetch the second checksum-verified series:

```bash
uv run download-binance-futures-data \
  --symbol ETHUSDT \
  --canonical-symbol ETH/USDT:USDT \
  --timeframe 1m \
  --start 2025-11-01 \
  --end 2026-08-01 \
  --output historical_data/binance-usdm-ethusdt-1m-2025-11_2026-07.csv
```

Then run the locked candidate:

```bash
uv run backtest \
  --input historical_data/binance-usdm-ethusdt-1m-2025-11_2026-07.csv \
  --exchange binance \
  --market-type perpetual \
  --symbol ETH/USDT:USDT \
  --source-timeframe 1m \
  --signal-timeframe 1h \
  --start 2025-11-01T00:00:00Z \
  --end 2026-08-01T00:00:00Z \
  --initial-equity 1000 \
  --order-notional 12 \
  --leverage 3 \
  --take-profit-roe 25 \
  --stop-loss-roe 1.5 \
  --trailing-activation-roe 3 \
  --trailing-interval-minutes 3 \
  --sar-consecutive-count 4 \
  --sar-close-consecutive-count 2 \
  --taker-fee-bps 5 \
  --slippage-bps 1 \
  --allow-proxy-data \
  --output-dir backtest_results/fresh-holdout-2025-11_2026-07/candidate
```

For the baseline comparison, substitute signal timeframe `30m`, TP `15`, SL
`3`, trailing activation `7`, and output directory `baseline`.

The generated detailed artifacts are:

- `backtest_results/parameter-sweep-2025/train_results.csv`;
- `backtest_results/parameter-sweep-2025/selected_evaluation.csv`;
- `backtest_results/parameter-sweep-2025/summary.json`; and
- `backtest_results/fresh-holdout-2025-11_2026-07/`.

They are intentionally untracked and reproducible using the grid command in
[`backtesting.md`](backtesting.md) and the confirmation commands above.
