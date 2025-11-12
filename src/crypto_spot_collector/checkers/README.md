# トレーディングシグナルチェッカー

このモジュールは、市場データから取引シグナルを検出するためのチェッカークラスを含んでいます。

## 概要

チェッカーシステムは拡張可能に設計されており、コアの取引ロジックを変更することなく、複数の取引戦略を実装できます。

## 基底クラス

すべてのチェッカーは `SignalChecker` 基底クラスを継承し、共通のインターフェースを提供します：

```python
from crypto_spot_collector.checkers.base_checker import SignalChecker

class SignalChecker(ABC):
    @abstractmethod
    def check(self, df: pd.DataFrame, **kwargs) -> bool:
        """提供されたDataFrame内の取引シグナルをチェックします。"""
        pass
```

## 利用可能なチェッカー

### SARChecker

`SARChecker` はパラボリックSARインジケーターに基づいて買いシグナルを検出します。

**使い方:**

```python
from crypto_spot_collector.checkers.sar_checker import SARChecker

# 希望する連続カウントでチェッカーを初期化
checker = SARChecker(consecutive_positive_count=3)

# SARインジケーターを含むDataFrameでシグナルをチェック
signal_detected = checker.check(df)
```

**シグナルロジック:**

このチェッカーは、NaN値の後に現れる正確にN個の連続した正のSAR値を探します。ここでNは `consecutive_positive_count` です。これは潜在的な強気トレンド転換を示します。

**パラメータ:**

- `consecutive_positive_count` (int): 買いシグナルに必要な連続した正のSAR値の数（デフォルト: 3）

## 新しいチェッカーの作成

新しい取引戦略を作成するには、`SignalChecker` を継承します：

```python
from crypto_spot_collector.checkers.base_checker import SignalChecker
import pandas as pd

class MyCustomChecker(SignalChecker):
    def __init__(self, custom_param: int = 10):
        self.custom_param = custom_param
    
    def check(self, df: pd.DataFrame, **kwargs) -> bool:
        # ここにシグナル検出ロジックを実装
        # 買いシグナルが検出された場合はTrue、それ以外はFalseを返す
        return False
```

取引ロジックで使用する：

```python
checker = MyCustomChecker(custom_param=20)
if checker.check(df):
    # 注文を実行
    pass
```
