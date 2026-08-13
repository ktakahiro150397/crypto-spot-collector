"""Deterministic event-driven replay of the Hyperliquid perpetual SAR strategy."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum

import pandas as pd
from ta.trend import PSARIndicator

from crypto_spot_collector.checkers.sar_checker import SARChecker
from crypto_spot_collector.exchange.trailingstop.trailingstop_manager import (
    TrailingStopManagerHyperLiquid,
)
from crypto_spot_collector.exchange.types import PositionSide
from crypto_spot_collector.trading.config import timeframe_milliseconds
from crypto_spot_collector.trading.strategy import (
    SarSignalDecision,
    evaluate_sar_signal,
)

from .data import CandleSeries, CandleSeriesKey, MarketType, resample_ohlcv
from .regime import PreparedEntryFilter


class BacktestConfigError(ValueError):
    """Raised when a backtest configuration cannot be replayed safely."""


class PendingAction(StrEnum):
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE = "close"


@dataclass(frozen=True)
class BacktestConfig:
    signal_timeframe: str = "30m"
    initial_equity: float = 1_000.0
    order_notional: float = 12.0
    leverage: int = 3
    take_profit_roe: float = 15.0
    stop_loss_roe: float = 3.0
    trailing_activation_roe: float = 7.0
    trailing_interval_minutes: int = 3
    sar_consecutive_count: int = 4
    sar_close_consecutive_count: int = 2
    taker_fee_bps: float = 0.0
    slippage_bps: float = 0.0
    sar_step: float = 0.02
    sar_max_step: float = 0.2
    close_open_position_at_end: bool = True
    allow_proxy_data: bool = False

    def validate(self, source_timeframe: str) -> None:
        positive_values = {
            "initial_equity": self.initial_equity,
            "order_notional": self.order_notional,
            "take_profit_roe": self.take_profit_roe,
            "stop_loss_roe": self.stop_loss_roe,
            "trailing_activation_roe": self.trailing_activation_roe,
            "sar_step": self.sar_step,
            "sar_max_step": self.sar_max_step,
        }
        for name, value in positive_values.items():
            if not math.isfinite(value) or value <= 0:
                raise BacktestConfigError(f"{name} must be finite and positive")
        if not 1 <= self.leverage <= 50:
            raise BacktestConfigError("leverage must be between 1 and 50")
        if self.trailing_activation_roe >= self.take_profit_roe:
            raise BacktestConfigError(
                "trailing activation ROE must be lower than take-profit ROE"
            )
        if self.trailing_interval_minutes <= 0:
            raise BacktestConfigError("trailing interval must be positive")
        if self.sar_consecutive_count <= 0 or self.sar_close_consecutive_count <= 0:
            raise BacktestConfigError("SAR consecutive counts must be positive")
        if self.taker_fee_bps < 0 or not math.isfinite(self.taker_fee_bps):
            raise BacktestConfigError("taker fee must be finite and non-negative")
        if self.slippage_bps < 0 or not math.isfinite(self.slippage_bps):
            raise BacktestConfigError("slippage must be finite and non-negative")
        source_ms = _timeframe_ms(source_timeframe)
        signal_ms = _timeframe_ms(self.signal_timeframe)
        if signal_ms < source_ms or signal_ms % source_ms != 0:
            raise BacktestConfigError(
                "signal timeframe must be an integer multiple of source timeframe"
            )
        trailing_ms = self.trailing_interval_minutes * 60_000
        if trailing_ms % source_ms != 0:
            raise BacktestConfigError(
                "source timeframe must evenly divide the trailing interval"
            )
        if self.order_notional / self.leverage > self.initial_equity:
            raise BacktestConfigError("initial equity does not cover entry margin")


@dataclass
class OpenPosition:
    side: PositionSide
    entry_time: pd.Timestamp
    entry_price: float
    quantity: float
    entry_fee: float
    take_profit_price: float
    funding_paid: float = 0.0


@dataclass(frozen=True)
class TradeRecord:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    entry_fee: float
    exit_fee: float
    funding: float
    net_pnl: float
    exit_reason: str

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["entry_time"] = self.entry_time.isoformat()
        values["exit_time"] = self.exit_time.isoformat()
        return values


@dataclass(frozen=True)
class BacktestResult:
    summary: dict[str, object]
    trades: pd.DataFrame
    equity_curve: pd.DataFrame


SignalEvaluator = Callable[[pd.DataFrame], SarSignalDecision]


@dataclass(frozen=True)
class PreparedSarSignals:
    """Precomputed SAR decisions reusable across execution-only parameters."""

    series_key: CandleSeriesKey
    source_start_ms: int
    source_end_ms: int
    source_candle_count: int
    signal_timeframe: str
    sar_step: float
    sar_max_step: float
    sar_consecutive_count: int
    decisions_by_close_ms: dict[int, SarSignalDecision]


TRADE_COLUMNS = [
    "entry_time",
    "exit_time",
    "side",
    "entry_price",
    "exit_price",
    "quantity",
    "gross_pnl",
    "entry_fee",
    "exit_fee",
    "funding",
    "net_pnl",
    "exit_reason",
]


class PerpetualSarBacktester:
    """Replay the Hyperliquid strategy with native or explicit proxy data."""

    def __init__(
        self,
        config: BacktestConfig,
        *,
        signal_evaluator: SignalEvaluator | None = None,
    ) -> None:
        self.config = config
        checker = SARChecker(consecutive_count=config.sar_consecutive_count)
        self._signal_evaluator = signal_evaluator or (
            lambda frame: evaluate_sar_signal(frame, checker)
        )
        self._entry_filter_id: str | None
        self._entry_regime: str | None
        self._reset()

    def prepare_signals(self, series: CandleSeries) -> PreparedSarSignals:
        """Prepare decisions once for repeated execution-parameter runs."""

        self._validate_series(series)
        self.config.validate(series.key.timeframe)
        signal_columns = ["timestamp", "open", "high", "low", "close", "volume"]
        if self.config.signal_timeframe == series.key.timeframe:
            signals = series.frame.loc[:, signal_columns]
        else:
            signals = resample_ohlcv(
                series.frame,
                source_timeframe=series.key.timeframe,
                target_timeframe=self.config.signal_timeframe,
            )
        signals = _with_sar(signals, self.config.sar_step, self.config.sar_max_step)
        signal_ms = _timeframe_ms(self.config.signal_timeframe)
        decisions: dict[int, SarSignalDecision] = {}
        for index, timestamp in enumerate(signals["timestamp"]):
            close_ms = int(pd.Timestamp(timestamp).timestamp() * 1000) + signal_ms
            decisions[close_ms] = self._signal_evaluator(signals.iloc[: index + 1])
        return PreparedSarSignals(
            series_key=series.key,
            source_start_ms=_timestamp_ms(series.frame.iloc[0]["timestamp"]),
            source_end_ms=_timestamp_ms(series.frame.iloc[-1]["timestamp"]),
            source_candle_count=len(series.frame),
            signal_timeframe=self.config.signal_timeframe,
            sar_step=self.config.sar_step,
            sar_max_step=self.config.sar_max_step,
            sar_consecutive_count=self.config.sar_consecutive_count,
            decisions_by_close_ms=decisions,
        )

    def run(
        self,
        series: CandleSeries,
        *,
        prepared_signals: PreparedSarSignals | None = None,
        prepared_entry_filter: PreparedEntryFilter | None = None,
    ) -> BacktestResult:
        self._validate_series(series)
        self.config.validate(series.key.timeframe)
        prepared = prepared_signals or self.prepare_signals(series)
        self._validate_prepared_signals(series, prepared)
        if prepared_entry_filter is not None:
            self._validate_prepared_entry_filter(series, prepared_entry_filter)
        self._reset()
        self._entry_filter_id = (
            prepared_entry_filter.config.identifier
            if prepared_entry_filter is not None
            else None
        )
        base = series.frame
        source_ms = _timeframe_ms(series.key.timeframe)
        source_delta = pd.Timedelta(milliseconds=source_ms)
        timestamps = base["timestamp"].array
        opens = base["open"].to_numpy(dtype=float, copy=False)
        highs = base["high"].to_numpy(dtype=float, copy=False)
        lows = base["low"].to_numpy(dtype=float, copy=False)
        closes = base["close"].to_numpy(dtype=float, copy=False)
        funding_rates = (
            base["funding_rate"].to_numpy(dtype=float, copy=False)
            if "funding_rate" in base.columns
            else None
        )

        for index in range(len(base)):
            timestamp = pd.Timestamp(timestamps[index])
            open_price = float(opens[index])
            close_price = float(closes[index])
            if self._pending_action is not None:
                self._execute_pending(timestamp, open_price)
            self._evaluate_protection(
                timestamp,
                candle_open=open_price,
                high=float(highs[index]),
                low=float(lows[index]),
            )
            funding_rate = (
                float(funding_rates[index]) if funding_rates is not None else None
            )
            self._apply_funding(close_price, funding_rate)
            candle_close = timestamp + source_delta
            self._record_equity(candle_close, close_price)
            self._update_trailing(candle_close, close_price, source_ms)

            close_ms = int(candle_close.timestamp() * 1000)
            if (
                prepared_entry_filter is not None
                and close_ms in prepared_entry_filter.direction_by_close_ms
            ):
                self._entry_regime = prepared_entry_filter.direction_by_close_ms[
                    close_ms
                ]
            decision = prepared.decisions_by_close_ms.get(close_ms)
            if decision is not None:
                self._apply_signal_decision(
                    decision,
                    entry_filter_active=prepared_entry_filter is not None,
                )

        if self._position is not None and self.config.close_open_position_at_end:
            final_time = pd.Timestamp(timestamps[-1]) + source_delta
            fill = self._adverse_fill(float(closes[-1]), self._exit_order_side())
            self._close_position(final_time, fill, "end_of_data")
            self._equity_rows[-1]["equity"] = self._cash

        trades = pd.DataFrame(
            [trade.as_dict() for trade in self._trades],
            columns=TRADE_COLUMNS,
        )
        equity = pd.DataFrame(self._equity_rows)
        return BacktestResult(
            summary=self._summary(series, trades, equity),
            trades=trades,
            equity_curve=equity,
        )

    def _validate_series(self, series: CandleSeries) -> None:
        if series.key.market_type is not MarketType.PERPETUAL:
            raise BacktestConfigError(
                "the perpetual SAR strategy requires perpetual candle data"
            )
        if series.key.exchange not in {"hyperliquid", "binance"}:
            raise BacktestConfigError(
                f"unsupported perpetual data exchange: {series.key.exchange}"
            )
        if series.key.exchange != "hyperliquid" and not self.config.allow_proxy_data:
            raise BacktestConfigError(
                "non-Hyperliquid data requires explicit allow_proxy_data"
            )

    def _validate_prepared_signals(
        self,
        series: CandleSeries,
        prepared: PreparedSarSignals,
    ) -> None:
        expected = (
            series.key,
            _timestamp_ms(series.frame.iloc[0]["timestamp"]),
            _timestamp_ms(series.frame.iloc[-1]["timestamp"]),
            len(series.frame),
            self.config.signal_timeframe,
            self.config.sar_step,
            self.config.sar_max_step,
            self.config.sar_consecutive_count,
        )
        actual = (
            prepared.series_key,
            prepared.source_start_ms,
            prepared.source_end_ms,
            prepared.source_candle_count,
            prepared.signal_timeframe,
            prepared.sar_step,
            prepared.sar_max_step,
            prepared.sar_consecutive_count,
        )
        if actual != expected:
            raise BacktestConfigError(
                "prepared SAR signals do not match series or signal configuration"
            )

    def _validate_prepared_entry_filter(
        self,
        series: CandleSeries,
        prepared: PreparedEntryFilter,
    ) -> None:
        expected = (
            series.key,
            _timestamp_ms(series.frame.iloc[0]["timestamp"]),
            _timestamp_ms(series.frame.iloc[-1]["timestamp"]),
            len(series.frame),
        )
        actual = (
            prepared.series_key,
            prepared.source_start_ms,
            prepared.source_end_ms,
            prepared.source_candle_count,
        )
        if actual != expected:
            raise BacktestConfigError(
                "prepared entry filter does not match the candle series"
            )

    def _reset(self) -> None:
        self._cash = self.config.initial_equity
        self._position: OpenPosition | None = None
        self._pending_action: PendingAction | None = None
        self._opposite_count = 0
        self._entry_filter_id = None
        self._entry_regime = None
        self._entry_signal_count = 0
        self._filtered_entry_signal_count = 0
        self._trailing = TrailingStopManagerHyperLiquid()
        self._trades: list[TradeRecord] = []
        self._equity_rows: list[dict[str, object]] = []

    def _apply_signal_decision(
        self,
        decision: SarSignalDecision,
        *,
        entry_filter_active: bool,
    ) -> None:
        if decision.direction is None:
            return
        if decision.long_signal and decision.short_signal:
            raise BacktestConfigError("signal evaluator returned conflicting entries")
        if self._position is not None:
            if decision.direction != self._position.side.value:
                self._opposite_count += 1
            else:
                self._opposite_count = 0
            if self._opposite_count >= self.config.sar_close_consecutive_count:
                self._pending_action = PendingAction.CLOSE
            return

        self._opposite_count = 0
        if decision.long_signal:
            self._entry_signal_count += 1
            if entry_filter_active and self._entry_regime != "long":
                self._filtered_entry_signal_count += 1
                return
            self._pending_action = PendingAction.OPEN_LONG
        elif decision.short_signal:
            self._entry_signal_count += 1
            if entry_filter_active and self._entry_regime != "short":
                self._filtered_entry_signal_count += 1
                return
            self._pending_action = PendingAction.OPEN_SHORT

    def _execute_pending(self, timestamp: pd.Timestamp, open_price: float) -> None:
        action = self._pending_action
        self._pending_action = None
        if action is PendingAction.OPEN_LONG and self._position is None:
            self._open_position(timestamp, open_price, PositionSide.LONG)
        elif action is PendingAction.OPEN_SHORT and self._position is None:
            self._open_position(timestamp, open_price, PositionSide.SHORT)
        elif action is PendingAction.CLOSE and self._position is not None:
            fill = self._adverse_fill(open_price, self._exit_order_side())
            self._close_position(timestamp, fill, "opposite_sar")

    def _open_position(
        self,
        timestamp: pd.Timestamp,
        reference_price: float,
        side: PositionSide,
    ) -> None:
        order_side = "buy" if side is PositionSide.LONG else "sell"
        fill = self._adverse_fill(reference_price, order_side)
        quantity = self.config.order_notional / fill
        fee = fill * quantity * self._fee_rate
        required_equity = self.config.order_notional / self.config.leverage + fee
        if self._cash < required_equity:
            raise BacktestConfigError("equity does not cover entry margin and fee")
        self._cash -= fee
        direction = 1 if side is PositionSide.LONG else -1
        take_profit = fill * (
            1 + direction * (self.config.take_profit_roe / 100) / self.config.leverage
        )
        stop_loss = fill * (
            1 - direction * (self.config.stop_loss_roe / 100) / self.config.leverage
        )
        self._position = OpenPosition(
            side=side,
            entry_time=timestamp,
            entry_price=fill,
            quantity=quantity,
            entry_fee=fee,
            take_profit_price=take_profit,
        )
        self._trailing.add_or_update_position(
            symbol="backtest",
            side=side,
            entry_price=fill,
            contracts=quantity,
            stoploss_order_id="backtest",
            initial_stoploss_price=stop_loss,
        )

    def _evaluate_protection(
        self,
        timestamp: pd.Timestamp,
        *,
        candle_open: float,
        high: float,
        low: float,
    ) -> None:
        if self._position is None:
            return
        trailing = self._trailing.get_position("backtest")
        if trailing is None:
            raise RuntimeError("backtest trailing state is missing")
        stop = trailing.current_stoploss_price
        target = self._position.take_profit_price
        if self._position.side is PositionSide.LONG:
            stop_hit = low <= stop
            target_hit = high >= target
            stop_reference = min(stop, candle_open) if stop_hit else stop
        else:
            stop_hit = high >= stop
            target_hit = low <= target
            stop_reference = max(stop, candle_open) if stop_hit else stop

        if stop_hit:
            reason = "trailing_stop" if trailing.trailing_activated else "stop_loss"
            fill = self._adverse_fill(stop_reference, self._exit_order_side())
            self._close_position(timestamp, fill, reason)
        elif target_hit:
            fill = self._adverse_fill(target, self._exit_order_side())
            self._close_position(timestamp, fill, "take_profit")

    def _apply_funding(
        self,
        close_price: float,
        funding_rate: float | None,
    ) -> None:
        if self._position is None or funding_rate is None:
            return
        direction = 1 if self._position.side is PositionSide.LONG else -1
        notional = self._position.quantity * close_price
        payment = direction * notional * funding_rate
        self._cash -= payment
        self._position.funding_paid += payment

    def _update_trailing(
        self,
        candle_close: pd.Timestamp,
        close_price: float,
        source_ms: int,
    ) -> None:
        if self._position is None:
            return
        close_ms = int(candle_close.timestamp() * 1000)
        trailing_ms = self.config.trailing_interval_minutes * 60_000
        if close_ms % trailing_ms != 0 or trailing_ms < source_ms:
            return
        trailing = self._trailing.get_position("backtest")
        if trailing is None:
            raise RuntimeError("backtest trailing state is missing")
        direction = 1 if self._position.side is PositionSide.LONG else -1
        roe = (
            direction
            * (close_price - self._position.entry_price)
            / self._position.entry_price
            * self.config.leverage
            * 100
        )
        if not trailing.trailing_activated:
            if roe >= self.config.trailing_activation_roe:
                self._trailing.activate_trailing("backtest", close_price)
        else:
            self._trailing.update_stoploss_price("backtest", close_price)

    def _close_position(
        self,
        timestamp: pd.Timestamp,
        fill: float,
        reason: str,
    ) -> None:
        position = self._position
        if position is None:
            raise RuntimeError("cannot close a missing backtest position")
        direction = 1 if position.side is PositionSide.LONG else -1
        gross = direction * (fill - position.entry_price) * position.quantity
        exit_fee = fill * position.quantity * self._fee_rate
        self._cash += gross - exit_fee
        net = gross - position.entry_fee - exit_fee - position.funding_paid
        self._trades.append(
            TradeRecord(
                entry_time=position.entry_time,
                exit_time=timestamp,
                side=position.side.value,
                entry_price=position.entry_price,
                exit_price=fill,
                quantity=position.quantity,
                gross_pnl=gross,
                entry_fee=position.entry_fee,
                exit_fee=exit_fee,
                funding=position.funding_paid,
                net_pnl=net,
                exit_reason=reason,
            )
        )
        self._position = None
        self._opposite_count = 0
        self._trailing.remove_position("backtest")

    def _record_equity(self, timestamp: pd.Timestamp, mark_price: float) -> None:
        unrealized = 0.0
        if self._position is not None:
            direction = 1 if self._position.side is PositionSide.LONG else -1
            unrealized = (
                direction
                * (mark_price - self._position.entry_price)
                * self._position.quantity
            )
        self._equity_rows.append(
            {"timestamp": timestamp.isoformat(), "equity": self._cash + unrealized}
        )

    def _summary(
        self,
        series: CandleSeries,
        trades: pd.DataFrame,
        equity: pd.DataFrame,
    ) -> dict[str, object]:
        final_equity = float(equity.iloc[-1]["equity"])
        equity_values = equity["equity"].astype(float)
        peaks = equity_values.cummax()
        drawdowns = (equity_values - peaks) / peaks
        if trades.empty:
            wins = trades
            losses = trades
        else:
            wins = trades.loc[trades["net_pnl"] > 0]
            losses = trades.loc[trades["net_pnl"] < 0]
        gross_profit = float(wins["net_pnl"].sum()) if not wins.empty else 0.0
        gross_loss = float(losses["net_pnl"].sum()) if not losses.empty else 0.0
        profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else None
        trade_count = len(trades)
        source_ms = _timeframe_ms(series.key.timeframe)
        first_open = pd.Timestamp(series.frame.iloc[0]["timestamp"])
        last_open = pd.Timestamp(series.frame.iloc[-1]["timestamp"])
        return {
            "series": series.key.as_dict(),
            "strategy_exchange": "hyperliquid",
            "data_mode": (
                "native" if series.key.exchange == "hyperliquid" else "proxy"
            ),
            "proxy_warning": (
                None
                if series.key.exchange == "hyperliquid"
                else "Results use Binance prices, volume, and market microstructure; "
                "they do not reproduce Hyperliquid execution."
            ),
            "data_provenance": series.provenance,
            "data_range": {
                "start": first_open.isoformat(),
                "end": (last_open + pd.Timedelta(milliseconds=source_ms)).isoformat(),
                "candle_count": len(series.frame),
            },
            "config": asdict(self.config),
            "funding_included": series.funding_available,
            "entry_filter_id": self._entry_filter_id,
            "entry_signal_count": self._entry_signal_count,
            "filtered_entry_signal_count": self._filtered_entry_signal_count,
            "trade_count": trade_count,
            "total_net_pnl": final_equity - self.config.initial_equity,
            "total_return_percent": (
                (final_equity / self.config.initial_equity - 1) * 100
            ),
            "max_drawdown_percent": abs(float(drawdowns.min())) * 100,
            "win_rate_percent": (len(wins) / trade_count * 100) if trade_count else 0.0,
            "profit_factor": profit_factor,
            "final_equity": final_equity,
        }

    def _exit_order_side(self) -> str:
        if self._position is None:
            raise RuntimeError("position is required to select an exit side")
        return "sell" if self._position.side is PositionSide.LONG else "buy"

    def _adverse_fill(self, reference: float, order_side: str) -> float:
        direction = 1 if order_side == "buy" else -1
        return reference * (1 + direction * self.config.slippage_bps / 10_000)

    @property
    def _fee_rate(self) -> float:
        return self.config.taker_fee_bps / 10_000


def _with_sar(frame: pd.DataFrame, step: float, max_step: float) -> pd.DataFrame:
    result = frame.copy()
    indicator = PSARIndicator(
        high=result["high"],
        low=result["low"],
        close=result["close"],
        step=step,
        max_step=max_step,
    )
    result["sar"] = indicator.psar()
    result["sar_up"] = indicator.psar_up()
    result["sar_down"] = indicator.psar_down()
    return result


def _timeframe_ms(timeframe: str) -> int:
    try:
        return int(timeframe_milliseconds(timeframe))
    except ValueError as exc:
        raise BacktestConfigError(str(exc)) from exc


def _timestamp_ms(value: object) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000)
