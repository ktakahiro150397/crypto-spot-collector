# 平均取得価格計算ロジック修正完了

## 修正内容

### 1. 新しいメソッド `get_current_position_and_avg_price()`
- **戻り値**: `(現在保有量, 平均取得価格)` のタプル
- **計算方式**: 移動平均法（加重平均）
- **売却考慮**: 適切に売却を考慮した正しい計算

### 2. 修正された `get_average_buy_price_by_symbol()`
- 新しいメソッドを呼び出して平均価格のみを返す
- 後方互換性を維持

## 計算ロジックの特徴

### ✅ 正しい処理
1. **購入時**: 加重平均で新しい平均取得価格を計算
   ```
   新平均価格 = (既存コスト + 新規購入コスト) / 新規総保有量
   ```

2. **売却時**: 保有量のみ減少、平均取得価格は変更されない
   ```
   売却後保有量 = 売却前保有量 - 売却量
   平均取得価格 = 変更なし
   ```

3. **手数料**: 購入コストに適切に含める
   ```
   購入コスト = 価格 × 数量 + 手数料
   ```

4. **時系列**: 取引の発生順序を考慮して逐次計算

5. **オーバーセル**: 保有量以上の売却を適切に処理

## 修正前後の比較

### 修正前（問題のあるロジック）
```python
# 誤った計算
avg_buy_price = 買いトレードの価格平均
avg_sell_price = 売りトレードの価格平均  # ❌ 売り価格を含めるのは誤り
result = (avg_buy_price + avg_sell_price) / 2  # ❌ 単純平均は不正確
```

### 修正後（正しいロジック）
```python
# 正しい移動平均計算
for trade in time_ordered_trades:
    if trade.position_type == "LONG":  # 購入
        total_cost += trade.price * trade.quantity + trade.fee
        total_quantity += trade.quantity
    elif trade.position_type == "SHORT":  # 売却
        if total_quantity > 0:
            current_avg_price = total_cost / total_quantity
            total_cost -= current_avg_price * sell_quantity
        total_quantity -= sell_quantity
```

## 実用例

```python
# 使用例
repo = TradeDataRepository()

# 現在の保有量と平均取得価格を取得
quantity, avg_price = repo.get_current_position_and_avg_price("BTC")
print(f"現在の保有: {quantity} BTC @ ${avg_price:,.2f}")

# 後方互換性（平均価格のみ取得）
avg_price = repo.get_average_buy_price_by_symbol("BTC")
print(f"平均取得価格: ${avg_price:,.2f}")
```

## テスト結果

✅ 全6テストケース合格:
- 単一購入取引
- 複数購入取引
- 購入・売却の組み合わせ
- 保有量以上の売却
- 複雑な取引シナリオ
- 取引履歴なしの場合

## まとめ

この修正により、暗号資産の平均取得価格が**売却を適切に考慮した正しい方法**で計算されるようになりました。会計原則に従った移動平均法を採用し、実際の保有コストを正確に反映します。
