# Multi-strategy maximum-profit exploration

## Decision

No candidate from this experiment qualifies for production. The maximum-profit
research candidate is a SAR-free four-hour time-series momentum strategy:

- direction: the sign of the 42-candle (seven-day) return;
- change direction only after the return exceeds `+1%` or falls below `-1%`;
- trade both long and short;
- leverage `1` with fixed `12` quote-currency notional;
- TP `8%` ROE, SL `6%` ROE, and trailing activation `7%` ROE; and
- close after two completed opposite-signal candles.

It produced the largest aggregate net PnL after the intermediate comparison,
but the final untouched XRP/BNB/DOGE gate rejected it. XRP earned `+9.8443`,
while BNB lost `-0.3959` and DOGE lost `-0.5525`. Only one of three final
instruments was profitable, below the pre-registered two-of-three requirement.
The aggregate `+8.8958` was therefore an XRP-concentrated outcome, not adequate
cross-instrument evidence.

The strongest SAR combination also failed the final gate. One-hour SAR with a
completed four-hour EMA `100` direction filter and ADX `14 >= 20`, TP `15`, SL
`1.5`, and trailing activation `4` returned `-0.9791` in aggregate on the final
three instruments. It was positive only on DOGE.

The defensible operational decision is:

- do not replace or modify the live strategy from this experiment;
- do not treat the current live SAR profit as evidence of positive expectancy;
- retain four-hour momentum as the leading SAR-free research hypothesis; and
- require a genuinely later time holdout before reconsidering deployment.

## Registered search contract

The development command loaded only checksum-verified Binance USD-M ETHUSDT
one-minute candles from `2025-01-01` through `2026-08-01`. It did not load any
validation instrument. The development range was divided into three folds:

1. `2025-01-01` through `2025-07-01`;
2. `2025-07-01` through `2026-01-01`; and
3. `2026-01-01` through `2026-08-01`.

The fixed grid contained 462 signal definitions across six families and all
three side modes (`both`, `long_only`, and `short_only`):

- Parabolic SAR, including completed four-hour EMA/ADX/ATR entry filters;
- price relative to EMA;
- fast/slow EMA crossover;
- Donchian breakout;
- time-series momentum; and
- RSI plus Bollinger-band mean reversion.

The first stage used the production-like TP `15`, SL `15`, and trailing `7`
exit. Maximum-profit and robust-score leaders from every family advanced to a
40-member exit grid. Screening and exit tuning used three-minute execution for
speed; the twelve frozen finalists were replayed at one-minute resolution.

All candidate runs used initial equity `1000`, fixed notional `12`, leverage
`1`, `5 bps` taker fee per fill, and `1 bp` adverse slippage. Leverage was not
optimized. The selection gate required all three development folds to be
positive, at least 30 trades, profit factor above one, and positive PnL after a
conservative stress that charges every open position `1 bp` at every eight-hour
funding boundary. Among passing candidates, total net PnL was the objective.

## Development results

The first-stage leader from each family, before exit tuning, was:

| family | best development signal at the fixed exit | net PnL | max DD | trades |
|---|---|---:|---:|---:|
| EMA price | 4h EMA200, both sides | +8.6136 | 0.1749% | 38 |
| SAR | 1h SAR + 4h EMA100/ADX20, short-only | +6.1874 | 0.3597% | 168 |
| EMA cross | 4h EMA10/30, short-only | +5.7172 | 0.5059% | 55 |
| Donchian | 1h, 55-candle, ADX20/ATR0.5%, short-only | +5.5554 | 0.4001% | 41 |
| momentum | 4h, 42-candle, 1% threshold, both sides | +5.0309 | 0.5082% | 76 |
| RSI/Bollinger | 4h, long-only | +2.1928 | 0.3271% | 12 |

The RSI/Bollinger leader did not meet the 20-trade screening minimum. After
exit tuning and one-minute precision replay, the important comparisons were:

| configuration | net PnL | fold returns | max DD | trades | PF | adverse-funding net |
|---|---:|---|---:|---:|---:|---:|
| 1h SAR + 4h EMA100/ADX20, TP15/SL1.5/trail4 | +10.1729 | +0.8550%, +0.0298%, +0.1310% | 0.3818% | 303 | 1.3658 | +9.7157 |
| 4h momentum 42/1%, TP8/SL6/trail7 | +8.6300 | +0.0681%, +0.3826%, +0.4102% | 0.4705% | 87 | 1.4279 | +7.8092 |
| 4h EMA200, TP15/SL15/trail7 | +8.6136 | all three positive | 0.1754% | 38 | 2.6801 | +8.1888 |
| prior 1h SAR + 4h EMA50/ADX30 | +2.8390 | one of three positive | 0.2497% | 154 | 1.3711 | +2.7922 |
| prior unfiltered 1h SAR | -0.4165 | one of three positive | 0.8866% | 969 | 0.9913 | -0.8929 |
| production 30m SAR | -10.6156 | one of three positive | 1.6763% | 1,869 | 0.9249 | -12.3280 |

The highest development net PnL locked the EMA100/ADX20 SAR combination before
any other instrument was downloaded.

## Intermediate validation and SAR-free promotion

The locked SAR combination was replayed without modification on full BTC and
SOL histories plus the later ETH period `2026-08-01` through `2026-08-24`.
It passed the registered aggregate gate but failed on BTC:

| instrument | SAR/EMA100/ADX20 | 4h momentum | production SAR |
|---|---:|---:|---:|
| BTC | -4.4363 | +0.2743 | -23.6058 |
| SOL | +7.1757 | +5.8192 | -24.1891 |
| later ETH | +0.2169 | +0.6916 | +0.9256 |
| aggregate | +2.9563 | +6.7851 | -46.8694 |
| adverse-funding aggregate | +1.9735 | +5.1555 | -50.4550 |

The momentum configuration was not selected from these validation results. It
was the maximum development PnL among non-SAR one-minute finalists passing the
same development gates, recorded in `precision_results.csv` before validation.
After it beat the locked SAR combination in intermediate aggregate PnL and was
positive on all three instruments, it was frozen as the sole candidate for a
second, newly downloaded holdout.

## Final untouched holdout

The promoted momentum candidate was evaluated once on XRP, BNB, and DOGE from
`2025-01-01` through `2026-08-24`:

| instrument | net PnL | stressed net | max DD | trades | PF |
|---|---:|---:|---:|---:|---:|
| XRP | +9.8443 | +9.0535 | 0.3612% | 89 | 1.5597 |
| BNB | -0.3959 | -1.3547 | 0.5497% | 68 | 0.9722 |
| DOGE | -0.5525 | -1.2797 | 0.5309% | 104 | 0.9805 |
| aggregate | +8.8958 | +6.4190 | — | 261 | — |

The aggregate and drawdown gates passed, but only one of three instruments was
positive. The candidate was rejected without parameter changes.

For completeness, the already locked SAR/EMA100/ADX20 candidate was also
replayed unchanged on the same final instruments. XRP returned `-4.6223`, BNB
`-0.5019`, and DOGE `+4.1450`; aggregate PnL was `-0.9791` and adverse-funding
PnL was `-2.2907`. It failed three of the five final checks.

## Interpretation

The experiment answers the original technical-indicator question directly:

- **SAR alone is not supported.** The production-like 30-minute SAR control
  lost heavily after costs across development and both validation groups.
- **EMA and ADX are useful filters, not a proof of edge.** They greatly reduce
  SAR turnover and loss, and can make some instruments profitable, but the best
  tuned combination did not transfer to the final group.
- **Four-hour time-series momentum is the strongest SAR-free signal tested.**
  It generated the largest validation and final aggregate profit, but that
  profit was insufficiently distributed across final instruments.
- **EMA200 is the strongest low-turnover SAR-free development alternative.**
  Its high profit factor and low drawdown merit a future pre-registered test,
  but this experiment did not promote it to an untouched final holdout.
- **Short-only is not universally superior.** Several family leaders were
  short-only during development, while later instrument-level side splits
  changed sign. The earlier ETH short-side pattern was regime-specific.

The current live SAR profit can be real realized PnL and still be luck. A small
sample dominated by one or two winners is compatible with a strategy whose
long-run proxy expectancy is negative after turnover costs. This experiment
does not prove that the live Hyperliquid implementation will lose, because
Binance USD-M data and assumed execution are proxies, but it removes the basis
for claiming that the present profit validates SAR.

## Reproduction

The development search is reproduced with:

```bash
uv run backtest-strategy-search search \
  --input historical_data/binance-usdm-ethusdt-1m-2025-01_2025-10.csv \
  --input historical_data/binance-usdm-ethusdt-1m-2025-11_2026-07.csv \
  --symbol ETH/USDT:USDT \
  --start 2025-01-01T00:00:00Z \
  --fold-boundaries 2025-07-01T00:00:00Z,2026-01-01T00:00:00Z \
  --end 2026-08-01T00:00:00Z \
  --taker-fee-bps 5 \
  --slippage-bps 1 \
  --workers 12 \
  --output-dir backtest_results/strategy-exploration-2025_2026-v2
```

`backtest-strategy-search confirm` accepts repeatable
`--dataset LABEL,SYMBOL,PATH,START,END` arguments and hashes every validation
CSV in `confirmation.json`. `promote` records the intermediate artifact hash
and freezes the exact candidate for a later holdout. Generated CSV, JSON, and
Markdown artifacts under `backtest_results/` are ignored by Git but fully
reproducible from checksum-verified input archives.

## Limitations

- Binance USD-M candles proxy Hyperliquid price and execution.
- Historical funding was not joined; a deliberately adverse 1 bp / eight-hour
  sensitivity was applied instead.
- Order-book depth, latency, partial fills, liquidation, and lot rounding are
  not modeled.
- Asset histories overlap in calendar time, so they test cross-instrument
  transfer more than a wholly new macroeconomic regime.
- Fixed `12` notional makes strategy comparisons fair but does not optimize
  capital allocation or portfolio-level exposure.
