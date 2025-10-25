# OHLCV Repository

MySQLのohlcv_dataテーブルからデータを取得するためのリポジトリクラスです。

## 特徴

- **時間足対応**: 1m, 5m, 10m, 1h, 2h, 4h, 6h の時間足に対応
- **キリのいい時間での取得**: 指定した時間足に応じて、キリのいい時間のデータのみを取得
  - 4h: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
  - 1h: 00:00, 01:00, 02:00, ...
  - 5m: 00:00, 00:05, 00:10, ...
- **柔軟な期間指定**: fromとtoの期間指定で必要な範囲のデータを取得
- **コンテキストマネージャ対応**: withステートメントでセッション管理を自動化

## 使用方法

### 基本的な使用例

```python
from datetime import datetime, timedelta
from crypto_spot_collector.repository import OHLCVRepository

# リポジトリのインスタンス作成（withステートメント推奨）
with OHLCVRepository() as repo:
    # 4時間足データの取得（過去7日間）
    to_date = datetime.now()
    from_date = to_date - timedelta(days=7)

    data = repo.get_ohlcv_data(
        symbol="BTCUSDT",
        interval="4h",
        from_datetime=from_date,
        to_datetime=to_date
    )

    for record in data:
        print(f"{record.timestamp_utc}: Close={record.close_price}")
```

### 対応している時間足

| 間隔 | 説明 | 取得される時間の例 |
|------|------|-------------------|
| `1m` | 1分足 | 00:00:00, 00:01:00, 00:02:00, ... |
| `5m` | 5分足 | 00:00:00, 00:05:00, 00:10:00, ... |
| `10m` | 10分足 | 00:00:00, 00:10:00, 00:20:00, ... |
| `1h` | 1時間足 | 00:00:00, 01:00:00, 02:00:00, ... |
| `2h` | 2時間足 | 00:00:00, 02:00:00, 04:00:00, ... |
| `4h` | 4時間足 | 00:00:00, 04:00:00, 08:00:00, ... |
| `6h` | 6時間足 | 00:00:00, 06:00:00, 12:00:00, 18:00:00 |

### 主要メソッド

#### `get_ohlcv_data(symbol, interval, from_datetime, to_datetime)`

指定した条件でOHLCVデータを取得します。

**引数:**
- `symbol`: 暗号通貨シンボル（例: "BTCUSDT"）
- `interval`: 時間足（"1m", "5m", "10m", "1h", "2h", "4h", "6h"）
- `from_datetime`: 開始日時（含む）
- `to_datetime`: 終了日時（含む）

**戻り値:** `List[OHLCVData]`

#### `get_ohlcv_data_count(symbol, interval, from_datetime, to_datetime)`

指定した条件に一致するレコード数を取得します。

#### `get_latest_ohlcv_data(symbol, limit)`

指定したシンボルの最新データを取得します。

**引数:**
- `symbol`: 暗号通貨シンボル
- `limit`: 取得する最大レコード数（デフォルト: 100）

#### `get_available_symbols()`

データベースで利用可能な暗号通貨シンボルの一覧を取得します。

#### `get_date_range(symbol)`

指定したシンボルで利用可能なデータの期間を取得します。

**戻り値:** `tuple[datetime, datetime]` (最古の日時, 最新の日時)

### 使用例集

#### 1. 4時間足データの取得

```python
with OHLCVRepository() as repo:
    data = repo.get_ohlcv_data(
        symbol="BTCUSDT",
        interval="4h",
        from_datetime=datetime(2025, 10, 1),
        to_datetime=datetime(2025, 10, 25)
    )

    print(f"取得したレコード数: {len(data)}")
    for record in data[:5]:  # 最初の5件を表示
        print(f"{record.timestamp_utc}: {record.close_price}")
```

#### 2. 1分足データのカウント

```python
with OHLCVRepository() as repo:
    count = repo.get_ohlcv_data_count(
        symbol="BTCUSDT",
        interval="1m",
        from_datetime=datetime(2025, 10, 25, 0, 0),
        to_datetime=datetime(2025, 10, 25, 23, 59)
    )

    print(f"1日分の1分足データ数: {count}")
```

#### 3. 利用可能なシンボルの確認

```python
with OHLCVRepository() as repo:
    symbols = repo.get_available_symbols()
    print(f"利用可能なシンボル: {symbols}")

    # 各シンボルのデータ期間を確認
    for symbol in symbols[:3]:  # 最初の3つのシンボル
        try:
            earliest, latest = repo.get_date_range(symbol)
            print(f"{symbol}: {earliest} ～ {latest}")
        except ValueError:
            print(f"{symbol}: データなし")
```

#### 4. 外部セッションの使用

```python
from crypto_spot_collector.database import get_db_session

# 既存のセッションを使用
session = get_db_session()
try:
    repo = OHLCVRepository(session=session)
    data = repo.get_latest_ohlcv_data("BTCUSDT", limit=10)

    # 他の処理...

finally:
    session.close()
```

### エラーハンドリング

```python
try:
    with OHLCVRepository() as repo:
        data = repo.get_ohlcv_data(
            symbol="INVALID_SYMBOL",
            interval="4h",
            from_datetime=datetime(2025, 10, 1),
            to_datetime=datetime(2025, 10, 25)
        )
except ValueError as e:
    print(f"エラー: {e}")
    # 例: "Cryptocurrency with symbol 'INVALID_SYMBOL' not found"
```

### テストスクリプト

作成したリポジトリをテストするには、以下のスクリプトを実行してください：

```bash
python src/crypto_spot_collector/scripts/test_ohlcv_repository.py
```

このスクリプトは、リポジトリの主要な機能をデモンストレーションし、実際のデータでの動作を確認できます。
