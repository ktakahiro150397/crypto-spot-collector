# Crypto Spot Collector

A Python application for collecting cryptocurrency spot prices.

## 開発環境

このプロジェクトは以下のツールを使用して開発されています：

- **Python 3.11+**
- **uv** - Pythonパッケージ管理
- **MySQL 8.0** - データベース
- **Dev Container** - 開発環境の標準化
- **Git** - バージョン管理

## セットアップ

### Dev Container使用（推奨）

1. VS Codeでプロジェクトを開く
2. Dev Containerで再度開くかプロンプトに従う
3. 自動的に環境がセットアップされます

### ローカル環境

1. uvをインストール:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. 依存関係をインストール:
```bash
uv sync --dev
```

3. Pre-commitフックをインストール:
```bash
uv run pre-commit install
```

## 開発

### コード品質

- **フォーマッター**: Black
- **インポート整理**: isort
- **リンター**: flake8
- **型チェック**: mypy
- **テスト**: pytest

### コマンド

```bash
# テストの実行
uv run pytest

# カバレッジ付きテスト
uv run pytest --cov=src

# コードフォーマット
uv run black src tests
uv run isort src tests

# リンター実行
uv run flake8 src tests

# 型チェック
uv run mypy src
```

## データベース

### MySQL設定

Dev Container内で以下の設定でMySQLが自動起動されます：

- **Host**: mysql
- **Port**: 3306
- **Database**: crypto_pachinko
- **User**: crypto_user
- **Password**: crypto_pass
- **Root Password**: rootpassword

### データベースコマンド

```bash
# データベース接続テスト
make db-test

# MySQLシェルに接続
make db-shell

# データベースリセット（注意：全データが削除されます）
make db-reset
```

### テーブル構成

- `cryptocurrencies` - 暗号通貨マスタ
- `ohlcv_data` - OHLCVデータ（通貨ごと、時間はUTC）
  - オープン、高値、安値、クローズ、取引量
- `trade_data` - 取引データ
  - 取引所名、ロング/ショート、現物/デリバティブ、レバレッジ倍率、時間（UTC）

## プロジェクト構造

```
crypto-spot-collector/
├── .devcontainer/          # Dev Container設定
├── src/
│   └── crypto_spot_collector/  # メインパッケージ
│       ├── apps/           # アプリケーションスクリプト
│       │   ├── buy_spot.py
│       │   ├── discord_appliation.py
│       │   ├── secrets.json.sample  # APIキー設定サンプル
│       │   ├── settings.json.sample # 公開設定サンプル
│       │   └── CONFIG.md   # 設定ファイルのドキュメント
│       ├── scripts/        # スクリプト
│       └── utils/          # ユーティリティ
├── tests/                  # テストファイル
├── docs/                   # ドキュメント
├── pyproject.toml          # プロジェクト設定
├── .gitignore              # Git無視ファイル
├── .gitattributes          # Git属性設定
└── .pre-commit-config.yaml # Pre-commit設定
```

## 設定ファイル

アプリケーションを実行する前に、設定ファイルを準備する必要があります。

### セットアップ手順

1. サンプルファイルをコピー:
```bash
cd src/crypto_spot_collector/apps
cp secrets.json.sample secrets.json
cp settings.json.sample settings.json
```

2. `secrets.json` に実際のAPIキーを設定
3. `settings.json` に取引設定やDiscord設定を記入

詳細は `src/crypto_spot_collector/apps/CONFIG.md` を参照してください。

## ライセンス

MIT License