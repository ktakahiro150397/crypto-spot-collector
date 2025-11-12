# Order Management Scripts

このディレクトリには、注文管理に関するスクリプトが含まれています。

## Scripts

### import_orders.py

取引所APIから全ての注文履歴を取得し、データベースに登録するスクリプトです。

**使用方法:**
```bash
python -m crypto_spot_collector.scripts.import_orders
```

**機能:**
- 指定されたシンボルの全ての注文（開注文、約定済み、キャンセル済み）を取得
- 重複チェックを行い、既に登録されている注文はスキップ
- 注文情報（注文ID、シンボル、売買方向、注文種類、価格、数量、ステータス、注文日時）をデータベースに保存

**注意:**
- 初回実行時は、secrets.jsonとsettings.jsonが正しく設定されている必要があります
- 大量の注文がある場合、実行に時間がかかる場合があります

### update_order_status.py

データベースに登録されている開注文のステータスを取引所APIで確認し、更新するスクリプトです。

**使用方法:**
```bash
python -m crypto_spot_collector.scripts.update_order_status
```

**機能:**
- データベース内の全ての開注文（status='open'）を取得
- 取引所APIで各注文のステータスを確認
- ステータスが変更されている場合（open -> closed, open -> canceled）、データベースを更新

**注意:**
- buy_spot.pyは1時間ごとに自動的に注文ステータスを更新します
- このスクリプトは、手動で注文ステータスを更新したい場合に使用します

## 初回セットアップ

1. データベースのテーブルを作成（既に作成されている場合はスキップ）:
```bash
# MySQLに接続して init.sql を実行
mysql -h localhost -u crypto_user -p crypto_pachinko < init.sql
```

2. 既存の注文履歴をインポート:
```bash
python -m crypto_spot_collector.scripts.import_orders
```

3. 注文ステータスを更新（オプション）:
```bash
python -m crypto_spot_collector.scripts.update_order_status
```

## データベース構造

### orders テーブル

| カラム名 | 型 | 説明 |
|---------|-----|------|
| id | INT | 主キー（自動採番） |
| order_id | VARCHAR(100) | 取引所の注文ID（ユニーク） |
| cryptocurrency_id | INT | 暗号通貨ID（外部キー） |
| symbol | VARCHAR(20) | 通貨ペア（例: BTC/USDT） |
| side | ENUM('buy', 'sell') | 売買方向 |
| order_type | ENUM('limit', 'market') | 注文種類 |
| price | DECIMAL(20, 8) | 注文価格 |
| quantity | DECIMAL(20, 8) | 注文数量 |
| status | ENUM('open', 'closed', 'canceled') | 注文ステータス |
| order_timestamp_utc | TIMESTAMP | 注文日時（UTC） |
| created_at | TIMESTAMP | レコード作成日時 |
| updated_at | TIMESTAMP | レコード更新日時 |

## 自動実行

buy_spot.pyは、注文を作成する際に自動的に以下を実行します:

1. 注文作成後、即座にデータベースに注文情報を記録（status='open'）
2. 1時間ごとに全ての開注文のステータスを確認し、更新

これにより、手動でスクリプトを実行しなくても、注文履歴とステータスが常に最新の状態に保たれます。
