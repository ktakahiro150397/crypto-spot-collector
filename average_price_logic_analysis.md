# 平均取得価格計算ロジックの問題点と修正案

## 現在のロジックの問題点

現在の `get_average_buy_price_by_symbol` メソッドは以下の問題があります：

```python
# 現在のロジック（問題あり）
avg_buy_price = 買いトレードの価格平均
avg_sell_price = 売りトレードの価格平均
平均取得価格 = (avg_buy_price + avg_sell_price) / 2
```

### 問題：
1. **売却は保有量の減少であり、平均取得価格に直接影響しない**
2. 売り価格を平均取得価格計算に含めるのは誤り
3. 数量（quantity）が考慮されていない

## 正しい計算方法

### 方法1: 移動平均法（推奨）
```python
def get_average_buy_price_by_symbol(self, symbol: str) -> tuple[float, float]:
    """現在の保有量と平均取得価格を計算"""

    # 時系列順に全取引を取得
    trades = session.query(TradeData).filter(...).order_by(TradeData.timestamp_utc)

    total_quantity = 0.0  # 現在の保有量
    total_cost = 0.0      # 累積購入コスト

    for trade in trades:
        if trade.position_type == "LONG":  # 購入
            # 新しい平均取得価格を計算
            new_quantity = total_quantity + trade.quantity
            total_cost += trade.price * trade.quantity + trade.fee
            total_quantity = new_quantity

        elif trade.position_type == "SHORT":  # 売却
            # 保有量を減らす（平均取得価格は変わらない）
            sell_quantity = min(trade.quantity, total_quantity)
            if total_quantity > 0:
                avg_price = total_cost / total_quantity
                total_cost -= avg_price * sell_quantity
            total_quantity -= sell_quantity
            total_quantity = max(0, total_quantity)  # 負の保有量を防ぐ

    if total_quantity > 0:
        return total_cost / total_quantity, total_quantity
    else:
        return 0.0, 0.0
```

### 方法2: 先入先出し法（FIFO）
購入したロットを個別に管理し、売却時は最も古いロットから消化

## 具体例

### 取引履歴:
1. 100 BTC @ $50,000 購入（手数料$50）
2. 200 BTC @ $60,000 購入（手数料$100）
3. 150 BTC @ $55,000 売却（手数料$75）

### 現在のロジック（誤り）:
- 買い平均: ($50,000 + $60,000) / 2 = $55,000
- 売り平均: $55,000
- 結果: ($55,000 + $55,000) / 2 = $55,000

### 正しい移動平均法:
1. 購入後: 300 BTC, 平均 $56,683 ((50,000×100 + 60,000×200 + 150) / 300)
2. 売却後: 150 BTC, 平均 $56,683 (変わらず)
3. 最終保有: 150 BTC @ $56,683

## 推奨修正
1. メソッド名を `get_current_position_and_avg_price` に変更
2. 現在保有量と平均取得価格の両方を返す
3. 時系列順に取引を処理
4. 手数料も考慮した正確な計算
