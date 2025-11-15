"""
Example demonstrating the corrected average price calculation.

This script shows how the new get_current_position_and_avg_price method
correctly calculates average acquisition price considering sales.
"""

from datetime import datetime
from unittest.mock import Mock


# Mock the repository for demonstration
class MockTradeDataRepository:
    def __init__(self):
        self.trades = []

    def add_trade(self, position_type, price, quantity, fee, timestamp):
        """Add a mock trade for testing."""
        trade = Mock()
        trade.position_type = position_type
        trade.price = price
        trade.quantity = quantity
        trade.fee = fee
        trade.timestamp_utc = timestamp
        self.trades.append(trade)

    def get_current_position_and_avg_price(self, symbol):
        """Calculate current position and average price (same logic as the real method)."""
        if not self.trades:
            return 0.0, 0.0

        total_quantity = 0.0
        total_cost = 0.0

        for trade in sorted(self.trades, key=lambda t: t.timestamp_utc):
            if trade.position_type == "LONG":  # Purchase
                purchase_cost = trade.price * trade.quantity + trade.fee
                total_cost += purchase_cost
                total_quantity += trade.quantity

            elif trade.position_type == "SHORT":  # Sale
                sell_quantity = min(trade.quantity, total_quantity)
                if total_quantity > 0:
                    current_avg_price = total_cost / total_quantity
                    total_cost -= current_avg_price * sell_quantity

                total_quantity -= sell_quantity
                total_quantity = max(0.0, total_quantity)

        if total_quantity > 0:
            average_price = total_cost / total_quantity
            return total_quantity, average_price
        else:
            return 0.0, 0.0


def demonstrate_average_price_calculation():
    """Demonstrate the correct average price calculation."""
    print("=== 暗号資産平均取得価格計算デモ ===\n")

    repo = MockTradeDataRepository()

    # Scenario 1: Simple buy and hold
    print("シナリオ1: シンプルな購入と保有")
    repo.add_trade("LONG", 50000, 1.0, 50, datetime(2025, 1, 1))
    quantity, avg_price = repo.get_current_position_and_avg_price("BTC")
    print(f"取引後: {quantity} BTC @ ${avg_price:,.2f}")
    print(f"計算: ($50,000 × 1.0 + $50) / 1.0 = ${avg_price:,.2f}\n")

    # Scenario 2: Multiple purchases (dollar cost averaging)
    print("シナリオ2: 複数回購入（ドルコスト平均法）")
    repo.add_trade("LONG", 60000, 2.0, 100, datetime(2025, 1, 15))
    quantity, avg_price = repo.get_current_position_and_avg_price("BTC")
    print(f"2回目の購入後: {quantity} BTC @ ${avg_price:,.2f}")
    print(f"計算: ($50,050 + $120,100) / 3.0 = ${avg_price:,.2f}\n")

    # Scenario 3: Partial sale
    print("シナリオ3: 一部売却")
    repo.add_trade("SHORT", 55000, 1.5, 75, datetime(2025, 2, 1))
    quantity, avg_price = repo.get_current_position_and_avg_price("BTC")
    print(f"売却後: {quantity} BTC @ ${avg_price:,.2f}")
    print(f"平均取得価格は変わらず ${avg_price:,.2f} のまま\n")

    # Scenario 4: Additional purchase after sale
    print("シナリオ4: 売却後の追加購入")
    repo.add_trade("LONG", 45000, 1.0, 45, datetime(2025, 2, 15))
    quantity, avg_price = repo.get_current_position_and_avg_price("BTC")
    print(f"追加購入後: {quantity} BTC @ ${avg_price:,.2f}")

    # Calculate the weighted average manually for verification
    remaining_cost = 56716.67 * 1.5  # Previous holdings cost
    new_cost = 45000 * 1.0 + 45      # New purchase cost
    total_cost = remaining_cost + new_cost
    total_quantity = 1.5 + 1.0
    manual_avg = total_cost / total_quantity
    print(
        f"手動計算: (${remaining_cost:,.2f} + ${new_cost:,.2f}) / {total_quantity} = ${manual_avg:,.2f}\n")

    # Scenario 5: Complete liquidation
    print("シナリオ5: 完全売却")
    repo.add_trade("SHORT", 70000, 2.5, 175, datetime(2025, 3, 1))
    quantity, avg_price = repo.get_current_position_and_avg_price("BTC")
    print(f"完全売却後: {quantity} BTC @ ${avg_price:,.2f}")
    print("保有量ゼロのため平均取得価格も0\n")

    print("=== 計算ロジックの特徴 ===")
    print("✓ 購入時: 加重平均で新しい平均取得価格を計算")
    print("✓ 売却時: 保有量のみ減少、平均取得価格は不変")
    print("✓ 手数料: 取得コストに含めて計算")
    print("✓ 時系列: 取引の発生順序を考慮")
    print("✓ オーバーセル: 保有量以上の売却を適切に処理")


if __name__ == "__main__":
    demonstrate_average_price_calculation()
