# Entry candidate and profit-lock analysis

## Result

The 4h 42-candle time-series momentum entry with a 1% threshold was the only
candidate to pass the pre-registered retrospective robustness gate. Its fixed-exit
baseline made `+32.133381 USDT` across six symbols and four independently restarted
folds, with all four fold totals positive, five of six symbol totals positive, a
`1.309754` profit factor, and `+26.958381 USDT` after the adverse funding stress.

The proposed early profit lock did not help this entry. Moving from the 7% trailing
activation and entry floor to a 0.25% activation and 0.15% profit floor changed net
PnL from `+32.133381` to `-3.032596 USDT`, profit factor from `1.309754` to
`0.870537`, and positive folds from four to two. The early profit lock is rejected.

| candidate | net PnL | stressed net | PF | trades | positive folds | positive symbols | worst fold | passed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 30m SAR control | -101.258675 | -112.227425 | 0.888072 | 12,309 | 0/4 | 0/6 | -45.198465 | no |
| 1h SAR + completed 4h EMA100/ADX20 | +9.375630 | +6.171880 | 1.047331 | 1,779 | 3/4 | 4/6 | -7.522650 | no |
| 4h momentum 42 / 1% | +32.133381 | +26.958381 | 1.309754 | 460 | 4/4 | 5/6 | +2.497890 | yes |
| 4h EMA200 direction | +3.382978 | +0.655478 | 1.058466 | 274 | 3/4 | 4/6 | -3.456630 | no |

The pass gate required all four fold totals to be positive, at least four of six
symbol totals to be positive, profit factor above one, positive net PnL after a
one-basis-point funding charge every eight hours, and at least 120 trades.

## Fold and symbol robustness

The selected momentum baseline remained positive in every independently restarted
fold. The 2026-late fold is shorter than the other half-year folds.

| fold | baseline net | stressed net | trades | profit-lock net |
| --- | ---: | ---: | ---: | ---: |
| 2025-H1 | +18.146112 | +16.559862 | 153 | -0.974901 |
| 2025-H2 | +5.889041 | +4.405291 | 139 | -3.955795 |
| 2026-H1 | +2.497890 | +0.896640 | 131 | +0.223284 |
| 2026-late | +5.600338 | +5.096588 | 37 | +1.674817 |

| symbol | baseline net | baseline trades | profit-lock net | profit-lock trades |
| --- | ---: | ---: | ---: | ---: |
| BTC | +1.970232 | 62 | -0.199419 | 105 |
| ETH | +5.233003 | 78 | -2.757953 | 128 |
| SOL | +8.959152 | 82 | +0.817936 | 135 |
| XRP | +14.739189 | 82 | +0.447564 | 127 |
| BNB | -3.759890 | 67 | -0.492592 | 114 |
| DOGE | +4.991696 | 89 | -0.848133 | 147 |

The profit lock increased the trade count from 460 to 756 but converted four of
the six symbol totals to losses. This supports the interpretation that locking a
very small gain clipped the profitable tails rather than fixing a slow-stop-loss
problem.

## Fixed evaluation contract

- Binance USD-M one-minute proxy candles, 2025-01-01 through 2026-08-24.
- BTC, ETH, SOL, XRP, BNB, and DOGE.
- Four flat-start folds: 2025-H1, 2025-H2, 2026-H1, and 2026-late.
- Indicators are rebuilt using only candles inside each fold.
- 1x leverage, 12.5 USDT notional, TP/SL 15% ROE.
- Baseline trailing activation 7%, entry floor, three-minute observation.
- 4.322 bps taker fee and one bp adverse slippage per fill.
- Profit-lock ablation: 0.25% activation, 0.15% floor, one-minute observation.
- Higher-timeframe filters become available only after their candle closes.

The opposite-direction exit requires two completed decisions for every signal.
That corresponds to one hour for the 30m candidate, two hours for the 1h candidate,
and eight hours for the 4h candidates. Therefore this is a comparison of complete
signal contracts under fixed numeric exit parameters, not a pure entry-only causal
attribution.

The candidate definitions came from earlier exploration that overlaps this history,
so the folds are robustness slices rather than a never-seen holdout. Binance candles
also do not reproduce Hyperliquid fills, order-book state, or actual funding, and
one-minute OHLC cannot establish intraminute event order. Passing this retrospective
gate is not deployment approval.

The reproducible runner is
`crypto_spot_collector.scripts.evaluate_entry_candidates`; machine-readable detail
is written under `backtest_results/entry-candidates-2025_2026` when run locally.
