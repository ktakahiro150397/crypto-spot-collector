# マーケットデータプロバイダー

このモジュールは、テクニカルインジケーター付きのマーケットデータを取得するための統一されたインターフェースを提供します。

## 概要

`MarketDataProvider` クラスは、データベースからOHLCV（Open, High, Low, Close, Volume）データを取得し、SMA（単純移動平均）やSAR（パラボリックSAR）などの一般的に使用されるテクニカルインジケーターで強化するロジックをカプセル化します。

## 使い方

```python
from datetime import datetime, timedelta
from crypto_spot_collector.providers.market_data_provider import MarketDataProvider

# プロバイダーを初期化
provider = MarketDataProvider()

# インジケーター付きのデータを取得
df = provider.get_dataframe_with_indicators(
    symbol="BTC",
    interval="1h",
    from_datetime=datetime.now() - timedelta(days=14),
    to_datetime=datetime.now(),
    sma_windows=[50, 100],  # オプション、デフォルトは [50, 100]
    sar_config={"step": 0.02, "max_step": 0.2}  # オプション
)
```

## DataFrameのカラム

返されるDataFrameには以下のカラムが含まれます：

- `timestamp`: UTC タイムスタンプ
- `open`: 始値
- `high`: 高値
- `low`: 安値
- `close`: 終値
- `volume`: 取引量
- `sma_{window}`: 各ウィンドウサイズの単純移動平均（例: `sma_50`, `sma_100`）
- `sar`: パラボリックSAR値
- `sar_up`: 強気トレンド中のSAR値（弱気時はNaN）
- `sar_down`: 弱気トレンド中のSAR値（強気時はNaN）

## パラメータ

### get_dataframe_with_indicators

- `symbol` (str): 仮想通貨シンボル（例: 'BTC', 'ETH'）
- `interval` (Literal): 時間間隔 - "1m", "5m", "10m", "1h", "2h", "4h", "6h" のいずれか
- `from_datetime` (datetime): 開始日時（この日時を含む）
- `to_datetime` (datetime): 終了日時（この日時を含む）
- `sma_windows` (Optional[List[int]]): 計算するSMAウィンドウサイズのリスト（デフォルト: [50, 100]）
- `sar_config` (Optional[Dict[str, float]]): 'step' と 'max_step' キーを持つSAR設定（デフォルト: {"step": 0.02, "max_step": 0.2}）

## 例: カスタムインジケーター

異なるSMAウィンドウやSAR設定を使用する場合：

```python
# カスタムSMAウィンドウ
df = provider.get_dataframe_with_indicators(
    symbol="ETH",
    interval="4h",
    from_datetime=start,
    to_datetime=end,
    sma_windows=[20, 50, 200]  # 20、50、200期間のSMA
)

# カスタムSARパラメータ
df = provider.get_dataframe_with_indicators(
    symbol="SOL",
    interval="1h",
    from_datetime=start,
    to_datetime=end,
    sar_config={"step": 0.01, "max_step": 0.15}  # より緩やかなSAR
)
```

## メリット

1. **一貫性**: すべての取引戦略が同じデータ処理ロジックを使用することを保証
2. **保守性**: インジケーター計算の変更は一箇所で行うだけで済む
3. **拡張性**: 取引ロジックを変更せずに新しいインジケーターを簡単に追加できる
4. **テスト可能性**: データ取得と処理を独立してテストできる
