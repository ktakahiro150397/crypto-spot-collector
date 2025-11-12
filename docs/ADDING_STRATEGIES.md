# 例: 新しい取引戦略の追加

この例では、リファクタリングされたアーキテクチャを使用して新しい取引戦略を追加する方法を示します。

## ステップ1: 新しいチェッカーを作成

`SignalChecker` を継承する新しいチェッカークラスを作成します：

```python
# ファイル: src/crypto_spot_collector/checkers/crossover_checker.py

"""移動平均クロスオーバーシグナルチェッカーの実装。"""

import pandas as pd
from loguru import logger

from crypto_spot_collector.checkers.base_checker import SignalChecker


class MovingAverageCrossoverChecker(SignalChecker):
    """移動平均クロスオーバー買いシグナル用のチェッカー。"""

    def __init__(self, fast_period: int = 50, slow_period: int = 100) -> None:
        """
        MAクロスオーバーチェッカーを初期化します。

        Args:
            fast_period: 高速移動平均の期間
            slow_period: 低速移動平均の期間
        """
        self.fast_period = fast_period
        self.slow_period = slow_period

    def check(self, df: pd.DataFrame, **kwargs) -> bool:
        """
        MAクロスオーバー買いシグナルをチェックします。

        高速MAが低速MAを上抜けした時にシグナルが検出されます。

        Args:
            df: OHLCVデータとSMAインジケーターを含むDataFrame
            **kwargs: 追加パラメータ（未使用）

        Returns:
            クロスオーバー買いシグナルが検出された場合はTrue、それ以外はFalse
        """
        fast_col = f"sma_{self.fast_period}"
        slow_col = f"sma_{self.slow_period}"
        
        if fast_col not in df.columns or slow_col not in df.columns:
            logger.error(f"DataFrame missing required columns: {fast_col}, {slow_col}")
            return False

        if len(df) < 2:
            return False

        # 直近の期間で高速MAが低速MAを上抜けしたかチェック
        current_fast = df[fast_col].iloc[-1]
        current_slow = df[slow_col].iloc[-1]
        previous_fast = df[fast_col].iloc[-2]
        previous_slow = df[slow_col].iloc[-2]

        # クロスオーバー: 高速が低速以下だったが、今は高速が低速より上
        if pd.notna(current_fast) and pd.notna(current_slow):
            if previous_fast <= previous_slow and current_fast > current_slow:
                logger.info("MA Crossover signal: Fast MA crossed above Slow MA")
                return True

        return False
```

## ステップ2: buy_spot.pyで新しいチェッカーを使用

`check_signal` 関数を修正して新しいチェッカーを使用します：

```python
# buy_spot.py内で、簡単に戦略を切り替えることができます：

from crypto_spot_collector.checkers.sar_checker import SARChecker
from crypto_spot_collector.checkers.crossover_checker import MovingAverageCrossoverChecker

async def check_signal(
    startDate: datetime,
    endDate: datetime,
    symbol: str,
    timeframe: str,
    amountByUSDT: float,
    strategy: str = "sar"  # 戦略パラメータを追加
) -> None:
    """指定された戦略を使用して買いシグナルをチェックします。"""

    # インジケーター付きのデータを取得
    data_provider = MarketDataProvider()
    df = data_provider.get_dataframe_with_indicators(
        symbol=symbol,
        interval=timeframe,
        from_datetime=startDate,
        to_datetime=endDate,
        sma_windows=[50, 100],
        sar_config={"step": 0.02, "max_step": 0.2}
    )

    # 戦略に基づいてチェッカーを選択
    if strategy == "sar":
        checker = SARChecker(consecutive_positive_count=3)
    elif strategy == "ma_crossover":
        checker = MovingAverageCrossoverChecker(fast_period=50, slow_period=100)
    else:
        logger.error(f"Unknown strategy: {strategy}")
        return

    # 選択した戦略を使用してシグナルをチェック
    signal_detected = checker.check(df)
    
    if signal_detected:
        # 注文を実行...
        pass
```

## ステップ3: 設定で戦略を構成

`secrets.json` に戦略設定を追加します：

```json
{
  "settings": {
    "timeframes": [
      {
        "timeframe": "1h",
        "amountBuyUSDT": 10,
        "strategy": "sar",
        "consecutivePositiveCount": 3
      },
      {
        "timeframe": "4h",
        "amountBuyUSDT": 20,
        "strategy": "ma_crossover"
      }
    ]
  }
}
```

## このアーキテクチャのメリット

1. **関心の分離**: 取引ロジックとシグナル検出が分離されている
2. **テストが容易**: 各チェッカーを独立してテストできる
3. **複数の戦略**: 異なるタイムフレームで異なる戦略を実行できる
4. **コードの重複なし**: データ取得ロジックが一元化されている
5. **保守性**: ある戦略への変更が他の戦略に影響しない

## インジケーターの追加

DataFrameにさらにインジケーターを追加するには、`MarketDataProvider` を修正します：

```python
# market_data_provider.py 内で

def get_dataframe_with_indicators(
    self,
    ...
    rsi_period: int = 14,  # 新しいパラメータを追加
) -> pd.DataFrame:
    ...
    # RSIインジケーターを追加
    from ta.momentum import RSIIndicator
    rsi = RSIIndicator(close=df["close"], window=rsi_period)
    df["rsi"] = rsi.rsi()
    
    return df
```

チェッカーで使用する：

```python
class RSIChecker(SignalChecker):
    def check(self, df: pd.DataFrame, **kwargs) -> bool:
        if "rsi" not in df.columns:
            return False
        
        latest_rsi = df["rsi"].iloc[-1]
        return latest_rsi < 30  # 売られ過ぎの条件
```
