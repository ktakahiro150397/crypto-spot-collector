# ETH SAR regime-filter analysis

## Decision

The four-hour EMA/ADX filter materially reduces turnover, assumed fees, and
drawdown, but it does not yet establish a profitable strategy. The strongest
risk-adjusted training candidate is:

- entry regime: four-hour close above/below EMA `50`;
- trend strength: four-hour ADX `14` at or above `30`;
- entry signal: one-hour SAR;
- TP: `25%` ROE;
- SL: `1.5%` ROE; and
- trailing activation: `3%` ROE, evaluated every three minutes.

This candidate can continue as a research default. It must not be applied to
production from this experiment alone because its second confirmation period
remained slightly negative after assumed fees.

## Causal filter contract

At each completed four-hour candle, the filter calculates EMA and optional
ADX using that candle and earlier candles only. The state becomes available at
the four-hour close, so a one-hour SAR decision closing at the same timestamp
may use it for an order scheduled at the next one-minute open. Before indicator
warm-up, below the ADX threshold, or when close equals EMA, new entries are
denied.

The filter affects new entries only. Existing positions retain the original
TP, SL, trailing-stop, and opposite-SAR close behavior. A long SAR entry is
allowed only when four-hour close is above EMA; a short entry is allowed only
when it is below EMA.

## Experimental design

The comparison uses checksum-verified Binance USD-M `ETHUSDT` one-minute
perpetual klines as a Hyperliquid strategy proxy. Selection is restricted to
January through June 2025. July through October 2025 and the separately
downloaded November 2025 through July 2026 data are not selection inputs.

The 22 variants are:

- existing `30m / TP15 / SL3 / trail7` control;
- unfiltered `1h / TP25 / SL1.5 / trail3` control; and
- the one-hour control with four-hour EMA `20`, `50`, `100`, or `200`, each
  with ADX disabled or ADX `14` threshold `15`, `20`, `25`, or `30`.

All variants use initial equity `1000`, order notional `12`, leverage `3`,
four SAR entry confirmations, two opposite SAR close confirmations, `5 bps`
taker fee, `1 bp` adverse slippage, and no funding data. Every evaluation
phase starts flat and recalculates indicator warm-up.

The maximum-return selector uses training return. The risk-adjusted selector
uses training return minus maximum drawdown minus population standard
deviation of monthly returns. Both later periods are opened only after these
nominees are locked.

## Results

| configuration | Jan-Jun 2025 train | Jul-Oct 2025 holdout | Nov 2025-Jul 2026 confirmation | confirmation max DD | confirmation trades |
|---|---:|---:|---:|---:|---:|
| existing 30m control | -0.3187% | -0.1664% | -1.4220% | 1.5506% | 860 |
| unfiltered 1h SAR | +0.4202% | -0.3220% | -0.1437% | 0.5376% | 432 |
| 4h EMA50 + ADX30, 1h SAR | +0.3332% | +0.0366% | -0.0480% | 0.1460% | 56 |

The unfiltered one-hour strategy still has the highest training return. The
EMA50/ADX30 candidate wins only on the documented risk-adjusted score. Against
unfiltered one-hour SAR in the nine-month confirmation, it reduces absolute
loss by about 67%, maximum drawdown by about 73%, trades by about 87%, and
assumed taker fees from `5.1832` to `0.6708` equity units.

All 20 filtered variants were positive during training, with median return
`+0.3089%`, median maximum drawdown `0.1230%`, and median 83 trades. This is
broader than a single lucky parameter point. ADX thresholds `15` and `20`
gave the best median training returns; threshold `30` gave the smallest median
drawdown and the risk-adjusted nominee.

## Cost and side diagnosis

The nominee's nine-month confirmation gross PnL after modeled slippage was
`+0.1907`, but `0.6708` of assumed taker fees produced net PnL `-0.4801`.
Holding all other model assumptions fixed, its modeled taker-fee break-even is
about `1.42 bps`. Funding and Hyperliquid-specific execution remain absent, so
this is a diagnostic threshold, not a live profitability forecast.

The side split exposes a follow-up hypothesis:

| phase | long net PnL | short net PnL |
|---|---:|---:|
| train | +0.3989 | +2.9333 |
| holdout | -0.2160 | +0.5823 |
| confirmation | -1.3844 | +0.9042 |

Short trades were positive in all three phases while long trades deteriorated.
This observation was made after opening both later periods, so selecting a
short-only variant now would be in-sample reuse. It requires a newly untouched
period or different instruments before it can be treated as validation.

## Reproduction

```bash
uv run backtest-regime-sweep \
  --input historical_data/binance-usdm-ethusdt-1m-2025-01_2025-10.csv \
  --confirmation-input historical_data/binance-usdm-ethusdt-1m-2025-11_2026-07.csv \
  --exchange binance \
  --market-type perpetual \
  --symbol ETH/USDT:USDT \
  --source-timeframe 1m \
  --train-start 2025-01-01T00:00:00Z \
  --holdout-start 2025-07-01T00:00:00Z \
  --holdout-end 2025-11-01T00:00:00Z \
  --confirmation-start 2025-11-01T00:00:00Z \
  --confirmation-end 2026-08-01T00:00:00Z \
  --filter-timeframe 4h \
  --ema-periods 20,50,100,200 \
  --adx-period 14 \
  --adx-thresholds 15,20,25,30 \
  --initial-equity 1000 \
  --order-notional 12 \
  --leverage 3 \
  --sar-consecutive-count 4 \
  --sar-close-consecutive-count 2 \
  --taker-fee-bps 5 \
  --slippage-bps 1 \
  --workers 6 \
  --output-dir backtest_results/regime-filter-2025_2026
```

The ignored output directory contains `train_results.csv`,
`selected_evaluation.csv`, `summary.json`, and `report.md`.
