# Cross-asset portfolio arsenal analysis

## Decision

The strongest new research direction is a slow, cross-asset trend portfolio,
not a tighter stop or a higher-turnover entry rule. The retrospective leader is:

- daily decisions at the completed UTC candle close and next-open execution;
- both long and short positions across BTC, ETH, SOL, XRP, BNB, and DOGE;
- a 28-day time-series momentum direction;
- a 56-day EMA direction;
- a 28-day Donchian breakout direction carried forward until reversal;
- exposure only when at least two of those three directions agree;
- inverse seven-day realized-volatility weighting; and
- a volatility brake that can reduce, but never increase, the 75 USDT gross cap.

It earned `+62.534623 USDT` after normal modeled transaction costs,
`+52.176946` after the adverse funding stress, and `+56.962455` after doubling
transaction costs. Every one of the four independently restarted folds remained
positive under doubled transaction costs. This passes the retrospective research
gate but is not approved for deployment because all available history has already
been inspected.

## Search coverage

The run evaluated 432 pre-registered candidates over four folds. It covered seven
portfolio families, 4h/12h/1d decisions, long-only and long/short modes, 0.5-day
through 56-day lookbacks, top-one/top-two cross-sectional ranks, absolute-momentum
gates, and volatility management.

Every candidate used:

- initial equity `1,000 USDT` and maximum gross notional `75 USDT` at 1x;
- next-open execution after a completed signal candle;
- `4.322 bps` taker fee plus `1 bp` adverse slippage on every unit of turnover;
- flat liquidation at every fold end;
- an adverse `1 bp` funding charge at each eight-hour boundary; and
- a separate doubled-transaction-cost result.

The pass gate required all folds to be profitable after doubled costs, positive
adverse-funding PnL, at least 30 position changes, and at least half of adjacent
lookbacks in the same design neighborhood to survive doubled costs. Fifteen of 432
candidates passed; all fifteen were long/short trend strategies. Nine were
three-signal ensembles and six were Donchian breakouts. No long-only, reversal,
cross-sectional momentum, standalone EMA, or standalone time-series momentum
candidate passed every gate.

| family leader | normal net | funding stress | double-cost | positive cost folds | passed |
| --- | ---: | ---: | ---: | ---: | --- |
| trend ensemble, 1d/28d, vol-managed | +62.534623 | +52.176946 | +56.962455 | 4/4 | yes |
| Donchian, 4h/28d | +39.684426 | +29.086926 | +38.440408 | 4/4 | yes |
| EMA trend, 12h/28d, vol-managed | +38.189432 | +27.209432 | +31.755457 | 3/4 | no |
| time-series momentum, 12h/28d | +29.187536 | +18.237536 | +24.371126 | 3/4 | no |
| cross-sectional momentum, 12h/28d | +41.411826 | +30.461826 | +32.218071 | 3/4 | no |
| time-series reversal, 12h/3d | +25.196874 | +11.996874 | +6.915804 | 2/4 | no |
| cross-sectional reversal, 12h/3d | -26.905566 | -40.105566 | -53.588743 | 0/4 | no |

The result is a parameter region rather than one isolated optimum. Profitable
passing variants exist at 4h, 12h, and 1d. Three of four adjacent lookbacks in the
winning daily ensemble neighborhood remained positive after doubled costs.

## Fold and walk-forward results

The retrospective winner's fold results were:

| fold | normal net | funding stress | double-cost | max drawdown | average gross use |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2025-H1 | +11.193967 | +7.867180 | +9.355268 | 1.7534% | 81.69% |
| 2025-H2 | +29.751034 | +26.500144 | +28.089102 | 1.2467% | 78.52% |
| 2026-H1 | +18.339934 | +15.054934 | +16.638793 | 2.5998% | 80.66% |
| 2026-late | +3.249688 | +2.754688 | +2.879292 | 0.5806% | 40.74% |

A sequential selection simulation selected only from earlier folds and applied the
winner once to the next fold. Its three evaluation folds summed to `+23.985545`
normally, `+16.485545` after adverse funding, and `+18.269768` after doubled
transaction costs. The first step is an important weakness: a 12h/14d ensemble
chosen from 2025-H1 made `+2.395923` in 2025-H2 normally but fell to `-1.324077`
after funding and `-1.248317` after doubled transaction costs. The later two steps
selected the 1d/28d volatility-managed ensemble and remained positive under both
stresses.

## Concentration checks

The winning rule was positive on four of six symbols under normal, funding, and
doubled-cost accounting. ETH and DOGE contributed most of the profit, while BNB
and XRP detracted.

| symbol | normal net | funding stress | double-cost |
| --- | ---: | ---: | ---: |
| BTC | +7.071234 | +5.141306 | +6.019545 |
| ETH | +35.150183 | +33.256200 | +34.277325 |
| SOL | +2.244571 | +0.838564 | +1.509664 |
| XRP | -3.932380 | -5.293661 | -4.782704 |
| BNB | -2.943737 | -4.954218 | -4.057373 |
| DOGE | +24.944752 | +23.188756 | +23.995998 |

The rule was then frozen and rerun after removing each symbol in turn. Every
leave-one-out portfolio stayed positive in aggregate under normal, funding, and
doubled-cost accounting. Removing ETH still produced `+31.155252` after doubled
costs; removing DOGE produced `+44.294178`. Five of six omissions kept all four
doubled-cost folds positive. Removing BNB kept `+55.770020` aggregate doubled-cost
PnL but reduced the fold count to three of four because portfolio weights and
signals changed. No single winning symbol is essential, although ETH/DOGE
concentration remains a risk.

## Directions accepted, rejected, and deferred

| direction | outcome |
| --- | --- |
| Slow time-series trend ensemble | Best research hypothesis; freeze for future forward collection. |
| Donchian trend following | Strong independent secondary hypothesis; multiple timeframes passed. |
| Cross-sectional relative strength | Positive aggregate leader but failed one doubled-cost fold. |
| Standalone EMA or momentum | Useful components, but neither family passed every fold alone. |
| Short-horizon reversal | Some gross/normal profit, but unstable and cost-sensitive. |
| Early 0.25%/0.15% profit lock | Rejected in the preceding fixed-entry ablation; it destroyed trend tails. |
| Funding/carry | Not testable from the available OHLCV because historical funding was not joined. |
| Market making/order-flow imbalance | Requires tick trades, book depth, queue position, and latency data. |
| Pairs/cointegration | Deferred until a rolling stationarity protocol and borrow/funding series are available. |
| Machine learning/meta-labeling | Deferred: only about twenty months are available and no untouched holdout remains. |
| Options volatility/carry | Requires an options surface and executable bid/ask history not present here. |

The literature supports treating time-series momentum and volatility reduction as
serious priors, but it does not validate these crypto parameters. Moskowitz, Ooi,
and Pedersen document time-series momentum across liquid futures, Liu and Tsyvinski
report time-series momentum in cryptocurrency returns, and Moreira and Muir show
that reducing risk when volatility is high can improve factor portfolio outcomes.
Those papers motivated the families and risk brake; all numerical decisions here
come from this repository's replay.

## Limitations and next gate

This portfolio model is materially different from the stopped single-position SAR
bot. It has synchronized multi-symbol accounting, daily or sub-daily portfolio
rebalancing, and no per-position TP/SL. Production would require a new portfolio
coordinator, exposure reservations, atomic/reconciled leg changes, reduce-only
emergency protection, stale-price handling, and restart-safe target weights. None
of that has been authorized or implemented for live use.

The six histories and all calendar folds have already been viewed in earlier
research. Sequential walk-forward therefore checks process causality but is not a
genuinely untouched statistical holdout. Binance prices proxy Hyperliquid and the
model omits actual funding, spread/depth variation, partial fills, lot rounding,
liquidation, API latency, and short availability. The proper next gate is to freeze
the 1d/28d ensemble and 4h/28d Donchian secondary specification, collect later data
without modification, and evaluate them once after a meaningful forward window.

The reproducible runner is
`crypto_spot_collector.scripts.evaluate_portfolio_arsenal`. Machine-readable results,
source hashes, candidate folds, family leaders, walk-forward selections, symbol
contributions, and leave-one-out tests are written under
`backtest_results/portfolio-arsenal-2025_2026`.

## Research references

- Moskowitz, Ooi, and Pedersen, *Time Series Momentum*:
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463>
- Liu and Tsyvinski, *Risks and Returns of Cryptocurrency*:
  <https://doi.org/10.1093/rfs/hhaa113>
- Moreira and Muir, *Volatility Managed Portfolios*:
  <https://www.nber.org/papers/w22208>
