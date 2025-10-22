# Crypto Spot Collector

A Python application for collecting cryptocurrency spot prices.

## 開発環境

このプロジェクトは以下のツールを使用して開発されています：

- **Python 3.11+**
- **uv** - Pythonパッケージ管理
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

## プロジェクト構造

```
crypto-spot-collector/
├── .devcontainer/          # Dev Container設定
├── src/
│   └── crypto_spot_collector/  # メインパッケージ
├── tests/                  # テストファイル
├── docs/                   # ドキュメント
├── config/                 # 設定ファイル
├── pyproject.toml          # プロジェクト設定
├── .gitignore              # Git無視ファイル
├── .gitattributes          # Git属性設定
└── .pre-commit-config.yaml # Pre-commit設定
```

## ライセンス

MIT License