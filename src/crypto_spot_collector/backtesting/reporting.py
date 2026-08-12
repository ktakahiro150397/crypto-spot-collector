"""Stable artifact output for offline backtest results."""

from __future__ import annotations

import json
from pathlib import Path

from .engine import BacktestResult


def write_backtest_report(
    result: BacktestResult,
    output_directory: Path | str,
) -> dict[str, Path]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "summary.json"
    trades_path = output / "trades.csv"
    equity_path = output / "equity.csv"
    summary_path.write_text(
        json.dumps(result.summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result.trades.to_csv(trades_path, index=False, lineterminator="\n")
    result.equity_curve.to_csv(equity_path, index=False, lineterminator="\n")
    return {
        "summary": summary_path,
        "trades": trades_path,
        "equity": equity_path,
    }
