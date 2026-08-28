# BTC/ETH SAR timeframe and profit-lock analysis

## Decision

No tested timeframe qualifies for deployment. The early profit lock reduced
drawdown in several slower-timeframe runs, but it was net negative for BTC and
ETH in both the 2025 development period and the separate 2026 evaluation
period. Changing the signal timeframe does not rescue the current SAR entry
and exit contract under the tested costs.

The least-negative early-profit-lock result used four-hour signals with
clock-normalized 1/1 confirmations. It returned `-6.695704 USDT` in development
and `-1.948720 USDT` in evaluation. Its worst-symbol evaluation drawdown was
`0.2976%`, down from the corresponding baseline's `0.5172%`, but loss reduction
is not positive expectancy.

## Contract

- Data: checksum-verified Binance USD-M BTCUSDT and ETHUSDT one-minute proxy
  candles from 2025-01-01 through 2026-08-24.
- Development: 2025-01-01 through 2026-01-01.
- Evaluation: 2026-01-01 through 2026-08-24, started flat with fresh indicator
  state.
- Signal timeframes: 5m, 15m, 30m, 1h, 2h, and 4h.
- Exposure: 1x leverage and 12.5 USDT fixed notional per trade.
- Protection: 15% ROE take profit and stop loss.
- Costs: 4.322 bps taker fee per fill and 1 bp adverse slippage per fill.
- Baseline: 7% trailing activation, entry-price floor, three-minute polling.
- Candidate: 0.25% activation, 0.15% profit floor, one-minute polling.
- Funding: omitted because it is absent from the kline data.

The one-minute source cannot reproduce a 30-second poll. Activation is sampled
at the one-minute close, and the updated stop becomes effective on the next
one-minute candle. This avoids look-ahead and is favorable on slippage relative
to the earlier 3 bps stop sensitivity.

## Same confirmation counts

This comparison keeps four completed directional SAR candles for entry and two
opposite candles for close at every timeframe.

| timeframe | baseline development | profit-lock development | baseline evaluation | profit-lock evaluation |
| --- | ---: | ---: | ---: | ---: |
| 5m | -216.350048 | -216.529693 | -127.900755 | -129.880389 |
| 15m | -47.797984 | -55.636645 | -44.975842 | -45.040896 |
| 30m | -6.304102 | -20.354357 | -21.933920 | -26.144935 |
| 1h | -8.035545 | -12.426187 | -9.145778 | -7.844868 |
| 2h | -22.253619 | -14.917300 | +3.250268 | -5.106629 |
| 4h | -4.385340 | -6.702657 | -6.437901 | -4.388765 |

The positive two-hour baseline evaluation result came entirely from ETH
(`+3.929777`); BTC remained negative (`-0.679509`). The same configuration lost
`-22.253619` in development and therefore fails the temporal and
cross-instrument gates.

## Clock-normalized confirmations

This comparison approximates the current 30-minute strategy's two-hour entry
confirmation and one-hour close confirmation: 5m uses 24/12 candles, 15m uses
8/4, 30m uses 4/2, 1h uses 2/1, and 2h/4h use the minimum 1/1.

| timeframe | baseline development | profit-lock development | baseline evaluation | profit-lock evaluation |
| --- | ---: | ---: | ---: | ---: |
| 5m | -14.237134 | -13.572105 | -4.810905 | -9.156864 |
| 15m | -30.381309 | -47.787352 | -37.722818 | -36.329257 |
| 30m | -6.304102 | -20.354357 | -21.933920 | -26.144935 |
| 1h | -2.378732 | -10.290946 | -11.376188 | -13.516081 |
| 2h | -20.277827 | -13.095660 | -2.216045 | -9.529425 |
| 4h | -6.258930 | -6.695704 | -2.964967 | -1.948720 |

Normalizing elapsed confirmation time removes most of the five-minute
turnover, but it does not create a profitable configuration. Across both
confirmation contracts, every early-profit-lock candidate is negative in both
periods and no candidate is positive on both BTC and ETH.

## Interpretation

- Five- and fifteen-minute signals remain dominated by turnover and costs.
- One-hour signals are less damaging than the current 30-minute control, but
  the fixed early floor cuts too many trend winners.
- Two-hour performance changes sign by period and instrument, so its isolated
  evaluation profit is not stable evidence.
- Four-hour signals have the smallest losses and drawdowns, but still lack a
  positive entry edge. Further work should change or filter the signal rather
  than optimize the early floor against these same periods.

The defensible next research target is a pre-registered four-hour regime or
momentum hypothesis, or a one-hour SAR signal filtered by completed four-hour
trend state. It must be evaluated on a new untouched period or instruments;
these BTC/ETH periods are now analysis data and must not be reused as an
out-of-sample gate.

## Reproduction

Run from the `codex/backtest` worktree:

```powershell
uv run python -m crypto_spot_collector.scripts.evaluate_profit_lock_timeframes `
  --dataset "BTC,BTC/USDT:USDT,historical_data/binance-usdm-btcusdt-1m-2025-01_2026-08-23.csv" `
  --dataset "ETH,ETH/USDT:USDT,historical_data/binance-usdm-ethusdt-1m-2025-01_2025-10.csv,historical_data/binance-usdm-ethusdt-1m-2025-11_2026-07.csv,historical_data/binance-usdm-ethusdt-1m-2026-08-01_2026-08-23.csv" `
  --output-dir backtest_results/timeframe-profit-lock-2025_2026
```

The generated `summary.json` records every source CSV SHA-256. Detailed
aggregate and per-symbol results are in the same output directory.

## Limitations

- Binance USD-M prices and microstructure proxy Hyperliquid rather than
  reproducing it.
- Funding, latency distributions, partial fills, order-book depth, and lot
  rounding are omitted.
- One-minute OHLC cannot determine intraminute high/low ordering or simulate a
  30-second poll exactly.
- BTC and ETH are only two instruments, and all reported periods are now seen
  data.
