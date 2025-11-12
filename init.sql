-- MySQL初期化スクリプト
-- データベース: crypto_pachinko

USE crypto_pachinko;

-- 暗号通貨情報テーブル
CREATE TABLE IF NOT EXISTS cryptocurrencies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL UNIQUE COMMENT '通貨シンボル (BTC, ETH等)',
    name VARCHAR(100) NOT NULL COMMENT '通貨名',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) COMMENT='暗号通貨マスタテーブル';

-- OHLCVデータテーブル（通貨ごと）
CREATE TABLE IF NOT EXISTS ohlcv_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    cryptocurrency_id INT NOT NULL,
    open_price DECIMAL(20, 8) NOT NULL COMMENT 'オープン価格',
    high_price DECIMAL(20, 8) NOT NULL COMMENT '高値',
    low_price DECIMAL(20, 8) NOT NULL COMMENT '安値',
    close_price DECIMAL(20, 8) NOT NULL COMMENT 'クローズ価格',
    volume DECIMAL(20, 8) NOT NULL COMMENT '取引量',
    timestamp_utc TIMESTAMP NOT NULL COMMENT 'データ時刻（UTC）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cryptocurrency_id) REFERENCES cryptocurrencies(id),
    INDEX idx_crypto_timestamp (cryptocurrency_id, timestamp_utc),
    INDEX idx_timestamp_utc (timestamp_utc),
    UNIQUE KEY unique_crypto_timestamp (cryptocurrency_id, timestamp_utc)
) COMMENT='OHLCVデータテーブル';

-- 取引データテーブル
CREATE TABLE IF NOT EXISTS trade_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    cryptocurrency_id INT NOT NULL,
    exchange_name VARCHAR(50) NOT NULL COMMENT '取引所名',
    position_type ENUM('LONG', 'SHORT') NOT NULL COMMENT 'ロング/ショート',
    is_spot BOOLEAN NOT NULL COMMENT '現物かどうか（TRUE: 現物, FALSE: 先物/デリバティブ）',
    leverage_ratio DECIMAL(5, 2) DEFAULT 1.00 COMMENT 'レバレッジ倍率（現物の場合は1.00）',
    price DECIMAL(20, 8) NOT NULL COMMENT '取引価格',
    quantity DECIMAL(20, 8) NOT NULL COMMENT '取引数量',
    timestamp_utc TIMESTAMP NOT NULL COMMENT '取引時刻（UTC）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cryptocurrency_id) REFERENCES cryptocurrencies(id),
    INDEX idx_crypto_exchange_time (cryptocurrency_id, exchange_name, timestamp_utc),
    INDEX idx_timestamp_utc (timestamp_utc),
    INDEX idx_exchange_name (exchange_name),
    INDEX idx_position_type (position_type),
    INDEX idx_is_spot (is_spot)
) COMMENT='取引データテーブル';

-- 注文テーブル
CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(100) NOT NULL UNIQUE COMMENT '取引所の注文ID',
    cryptocurrency_id INT NOT NULL,
    symbol VARCHAR(20) NOT NULL COMMENT '通貨ペア (BTC/USDT等)',
    side ENUM('buy', 'sell') NOT NULL COMMENT '売買方向 (buy/sell)',
    order_type ENUM('limit', 'market') NOT NULL COMMENT '注文種類 (limit: 指値, market: 成り行き)',
    price DECIMAL(20, 8) NOT NULL COMMENT '注文価格',
    quantity DECIMAL(20, 8) NOT NULL COMMENT '注文数量',
    status ENUM('open', 'closed', 'canceled') NOT NULL DEFAULT 'open' COMMENT '注文ステータス (open: 注文中, closed: 約定済み, canceled: キャンセル済み)',
    order_timestamp_utc TIMESTAMP NOT NULL COMMENT '注文日時（UTC）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (cryptocurrency_id) REFERENCES cryptocurrencies(id),
    INDEX idx_order_id (order_id),
    INDEX idx_crypto_status (cryptocurrency_id, status),
    INDEX idx_symbol_status (symbol, status),
    INDEX idx_order_timestamp (order_timestamp_utc)
) COMMENT='注文テーブル';

-- 初期データの投入
INSERT IGNORE INTO cryptocurrencies (symbol, name) VALUES 
('BTC', 'Bitcoin'),
('ETH', 'Ethereum'),
('BNB', 'Binance Coin'),
('XRP', 'Ripple'),
('ADA', 'Cardano'),
('SOL', 'Solana'),
('DOGE', 'Dogecoin'),
('DOT', 'Polkadot'),
('MATIC', 'Polygon'),
('AVAX', 'Avalanche');

-- ユーザー権限の確認
SHOW GRANTS FOR 'crypto_user'@'%';